"""Portfolio-only interface skeleton. This module is intentionally non-runnable."""


class DiscordConfigManagerInterface:
    """Architectural surface of the private production implementation."""

    async def list_sources(self, *args, **kwargs):
        """Public portfolio signature only. Production logic is private."""
        raise NotImplementedError("Production implementation is private")

    async def list_sections(self, *args, **kwargs):
        """Public portfolio signature only. Production logic is private."""
        raise NotImplementedError("Production implementation is private")

    async def validate_change(self, *args, **kwargs):
        """Public portfolio signature only. Production logic is private."""
        raise NotImplementedError("Production implementation is private")

    async def create_backup(self, *args, **kwargs):
        """Public portfolio signature only. Production logic is private."""
        raise NotImplementedError("Production implementation is private")

    async def apply_override(self, *args, **kwargs):
        """Public portfolio signature only. Production logic is private."""
        raise NotImplementedError("Production implementation is private")

