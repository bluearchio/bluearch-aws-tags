"""Setup validation aliases backed by bluearch-core.

The shared setup contract is exposed at /api/v1/setup/* in core and the
product backends. Tag Manager keeps /api/v1/system/setup/* as a compatibility
alias for older frontend code.
"""

from fastapi import APIRouter, Depends

from ..dependencies import get_current_user, LocalUser
from ..schemas.common import SetupValidateResponse
from .system import get_iam_policy as system_iam_policy
from .system import validate_setup as system_validate_setup

router = APIRouter(prefix="/api/v1/setup", tags=["setup"])


@router.get("/validate", response_model=SetupValidateResponse)
async def validate_setup(current_user: LocalUser = Depends(get_current_user)):
    """Return setup validation from the shared core runtime."""
    return await system_validate_setup(current_user)


@router.get("/iam-policy")
async def get_iam_policy(current_user: LocalUser = Depends(get_current_user)):
    """Return the recommended IAM policy from bluearch-core."""
    return await system_iam_policy(current_user)
