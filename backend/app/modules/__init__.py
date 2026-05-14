# Module registry — import each module's models so Alembic autogenerate detects them.
from app.modules.identity import models as _identity_models  # noqa: F401
from app.modules.categories import models as _category_models  # noqa: F401
from app.modules.business_profile import models as _bp_models  # noqa: F401
