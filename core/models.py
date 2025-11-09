"""Database models for the Scavenger Hunt application."""

from django.db import models


class Participant(models.Model):
    """Represents a user authenticated through Ion."""

    ion_username = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=255, blank=True)
    email = models.EmailField(blank=True)
    graduation_year = models.PositiveIntegerField(null=True, blank=True)
    is_admin = models.BooleanField(default=False)
    last_login = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["ion_username"]

    def __str__(self) -> str:
        return self.display_name or self.ion_username
