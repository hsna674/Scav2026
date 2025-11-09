"""Views for the Scavenger Hunt core app."""

from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.http import HttpResponse, HttpResponseBadRequest, HttpResponseRedirect
from django.shortcuts import redirect, render
from django.utils import formats, timezone
from requests_oauthlib import OAuth2Session

from .models import Participant


SESSION_STATE_KEY = "ion_oauth_state"
SESSION_TOKEN_KEY = "ion_oauth_token"
SESSION_PARTICIPANT_KEY = "ion_participant_id"


def _missing_oauth_settings(require_secret: bool = False) -> list[str]:
    required = {
        "ION_CLIENT_ID": settings.ION_CLIENT_ID,
        "ION_REDIRECT_URI": settings.ION_REDIRECT_URI,
    }
    if require_secret:
        required["ION_CLIENT_SECRET"] = settings.ION_CLIENT_SECRET
    return [key for key, value in required.items() if not value]


def _create_oauth_session(state: str | None = None) -> OAuth2Session:
    return OAuth2Session(
        settings.ION_CLIENT_ID,
        redirect_uri=settings.ION_REDIRECT_URI,
        scope=settings.ION_SCOPE,
        state=state,
    )


def _extract_graduation_year(profile: dict[str, Any]) -> int | None:
    value = profile.get("graduation_year")
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_is_admin(profile: dict[str, Any]) -> bool:
    groups = profile.get("groups") or []
    if isinstance(groups, (list, tuple, set)):
        groups = {str(item).lower() for item in groups}
        if {"scavenger-admin", "ion-admin", "admin"} & groups:
            return True
    return bool(profile.get("is_admin") or profile.get("is_staff"))


def _build_display_name(profile: dict[str, Any]) -> str:
    first = (profile.get("first_name") or "").strip()
    last = (profile.get("last_name") or "").strip()
    if first or last:
        return (first + " " + last).strip()
    return profile.get("ion_username", "").strip()


def _get_logged_in_participant(request) -> Participant | None:
    participant_id = request.session.get(SESSION_PARTICIPANT_KEY)
    if not participant_id:
        return None
    try:
        return Participant.objects.get(pk=participant_id)
    except Participant.DoesNotExist:
        request.session.pop(SESSION_PARTICIPANT_KEY, None)
        return None


def _format_est(dt: timezone.datetime | None) -> str | None:
    if dt is None:
        return None
    localized = dt.astimezone(settings.SCAV_HUNT_TZ)
    return formats.date_format(localized, "N j, Y g:i A") + " ET"


def _hunt_window_status() -> tuple[bool, str, str]:
    now = timezone.now().astimezone(settings.SCAV_HUNT_TZ)
    start = settings.SCAV_HUNT_START
    end = settings.SCAV_HUNT_END

    if start and now < start:
        message = "The hunt hasn't opened yet. Doors open on {when}.".format(
            when=_format_est(start)
        )
        return False, "upcoming", message

    if end and now > end:
        message = "The hunt has ended. It closed on {when}.".format(when=_format_est(end))
        return False, "ended", message

    return True, "open", ""


def login_view(request):
    """Render the landing/login page."""

    participant = _get_logged_in_participant(request)
    if participant:
        return redirect("core:challenge")

    missing_settings = _missing_oauth_settings()
    context = {
        "missing_settings": missing_settings,
        "ion_scope": settings.ION_SCOPE,
        "ion_ready": not missing_settings,
    }
    return render(request, "core/login.html", context)


def oauth_start(request):
    """Start the Ion OAuth2 flow by redirecting to the provider."""

    missing_settings = _missing_oauth_settings()
    if missing_settings:
        raise ImproperlyConfigured(
            "Ion OAuth is not fully configured. Missing: "
            + ", ".join(missing_settings)
        )

    oauth = _create_oauth_session()
    authorization_url, state = oauth.authorization_url(settings.ION_AUTHORIZE_URL)
    request.session[SESSION_STATE_KEY] = state
    return HttpResponseRedirect(authorization_url)


def oauth_callback(request):
    """Handle the Ion OAuth2 callback and greet the authenticated user."""

    missing_settings = _missing_oauth_settings(require_secret=True)
    if missing_settings:
        raise ImproperlyConfigured(
            "Ion OAuth is not fully configured. Missing: "
            + ", ".join(missing_settings)
        )

    state = request.GET.get("state")
    code = request.GET.get("code")
    stored_state = request.session.pop(SESSION_STATE_KEY, None)

    if not state or state != stored_state:
        return HttpResponseBadRequest("Invalid OAuth state returned by Ion.")

    if not code:
        return HttpResponseBadRequest("Missing authorization code.")

    oauth = _create_oauth_session(state=state)

    try:
        token = oauth.fetch_token(
            settings.ION_TOKEN_URL,
            code=code,
            client_secret=settings.ION_CLIENT_SECRET,
        )
    except Exception as exc:  # pragma: no cover - network errors
        return HttpResponse(
            "Unable to complete authentication with Ion at this time.", status=502
        )

    request.session[SESSION_TOKEN_KEY] = token

    try:
        profile_response = oauth.get(settings.ION_PROFILE_URL)
        profile_response.raise_for_status()
        profile_data = profile_response.json()
    except Exception as exc:  # pragma: no cover - network errors
        return HttpResponse("Unable to load Ion profile data.", status=502)

    ion_username = profile_data.get("ion_username")
    if not ion_username:
        return HttpResponse("Ion did not return a username.", status=502)

    display_name = _build_display_name(profile_data) or ion_username

    participant, _created = Participant.objects.update_or_create(
        ion_username=ion_username,
        defaults={
            "display_name": display_name,
            "email": profile_data.get("tj_email") or profile_data.get("email", ""),
            "graduation_year": _extract_graduation_year(profile_data),
            "is_admin": _extract_is_admin(profile_data),
            "last_login": timezone.now(),
        },
    )

    request.session[SESSION_PARTICIPANT_KEY] = participant.pk

    return redirect("core:challenge")


def dashboard_view(request):
    """Show a minimal dashboard for authenticated participants."""

    participant = _get_logged_in_participant(request)
    if not participant:
        return redirect("core:login")

    context = {
        "participant": participant,
    }
    return render(request, "core/dashboard.html", context)


def challenge_view(request):
    """Display the challenge page or a closed notice based on hunt status."""

    participant = _get_logged_in_participant(request)
    if not participant:
        return redirect("core:login")

    is_open, state, message = _hunt_window_status()

    base_context = {
        "participant": participant,
        "hunt_state": state,
        "hunt_message": message,
        "hunt_starts_at": _format_est(settings.SCAV_HUNT_START),
        "hunt_ends_at": _format_est(settings.SCAV_HUNT_END),
    }

    if is_open or participant.is_admin:
        return render(request, "core/challenge.html", base_context)

    return render(request, "core/challenge_closed.html", base_context, status=403)
