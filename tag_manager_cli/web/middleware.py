"""Exception handlers mapping AWS errors to HTTP responses."""

from fastapi import Request
from fastapi.responses import JSONResponse


async def aws_client_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Map botocore ClientError to appropriate HTTP status codes."""
    error_code = exc.response.get("Error", {}).get("Code", "Unknown")  # type: ignore[attr-defined]
    error_message = exc.response.get("Error", {}).get("Message", str(exc))  # type: ignore[attr-defined]

    status_map = {
        "AccessDeniedException": 403,
        "AccessDenied": 403,
        "UnauthorizedAccess": 403,
        "AuthFailure": 403,
        "NotFound": 404,
        "NotFoundException": 404,
        "ResourceNotFoundException": 404,
        "NoSuchEntity": 404,
        "NoSuchBucket": 404,
        "Throttling": 429,
        "ThrottlingException": 429,
        "TooManyRequestsException": 429,
        "RequestLimitExceeded": 429,
        "LimitExceededException": 429,
        "ValidationException": 400,
        "ValidationError": 400,
        "InvalidParameterValue": 400,
        "InvalidParameter": 400,
        "MalformedPolicyDocument": 400,
    }

    status_code = status_map.get(error_code, 502)
    return JSONResponse(
        status_code=status_code,
        content={"detail": str(error_message), "code": error_code},
    )


async def no_credentials_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle missing AWS credentials."""
    return JSONResponse(
        status_code=503,
        content={
            "detail": "AWS credentials not configured. Run 'aws configure' or set AWS_PROFILE.",
            "code": "NoCredentials",
        },
    )


async def botocore_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle generic botocore errors."""
    return JSONResponse(
        status_code=502,
        content={
            "detail": "AWS service error: " + str(exc),
            "code": "AWSError",
        },
    )
