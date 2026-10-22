import sys
sys.path.insert(0, ".")
from app.models.user import User
print("User cols:", list(User.__table__.columns.keys()))
