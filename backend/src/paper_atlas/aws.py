from __future__ import annotations

import json
from typing import Any

from .config import get_settings


def check_connection() -> dict[str, Any]:
    """Validate the local AWS credential chain without printing credentials."""
    settings = get_settings()
    result: dict[str, Any] = {
        "profile": settings.aws_profile or "default credential chain",
        "region": settings.aws_region,
        "model_id_configured": bool(settings.bedrock_model_id),
        "authenticated": None,
        "status": "not_checked",
    }
    try:
        import boto3
    except ImportError:
        result.update({"message": "boto3 is not installed, so AWS authentication was not checked. Run: python -m pip install -e ."})
        return result

    try:
        session = boto3.Session(profile_name=settings.aws_profile, region_name=settings.aws_region)
        identity = session.client("sts").get_caller_identity()
        result.update({
            "authenticated": True,
            "status": "authenticated",
            "account": identity.get("Account"),
            "arn": identity.get("Arn"),
            "message": "AWS credentials are available to this local user.",
        })
    except Exception as exc:  # boto3 exposes several credential/provider-specific errors
        result.update({"authenticated": False, "status": "authentication_failed", "message": str(exc)})
    return result


def main() -> None:
    print(json.dumps(check_connection(), indent=2))


if __name__ == "__main__":
    main()
