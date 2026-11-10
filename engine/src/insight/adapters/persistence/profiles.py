from importlib.resources import files

from insight.domain.contracts import PlatformError, Profile


class BundledProfiles:
    def get(self, profile_ref: str) -> Profile:
        name, _, revision = profile_ref.partition("@")
        if not name or any(c not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for c in name):
            raise PlatformError("INVALID_SPEC", "Invalid profile reference")
        resource = files("insight").joinpath("resources", "profiles", name + ".json")
        if not resource.is_file():
            raise PlatformError("UNSUPPORTED_CAPABILITY", "Profile is not installed")
        profile = Profile.model_validate_json(resource.read_bytes())
        if str(profile.version) != revision:
            raise PlatformError("REVISION_CONFLICT", "Profile version is not installed")
        return profile
