from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, UniqueConstraint
from datetime import datetime
from app.db.database import Base

class Tenant(Base):
    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    
    # Meta WhatsApp credentials per professional (populated during onboarding / signup)
    whatsapp_phone_number_id = Column(String, unique=True, index=True, nullable=False)
    whatsapp_access_token = Column(String, nullable=False)
    
    # Google Calendar OAuth 2.0 Credentials
    google_access_token = Column(String, nullable=True)
    google_refresh_token = Column(String, nullable=True)
    google_token_expiry = Column(DateTime, nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_phone = Column(String, nullable=False)
    
    state = Column(String, default="idle")  # idle, select_time, confirming
    temp_date = Column(String, nullable=True) # YYYY-MM-DD
    temp_time = Column(String, nullable=True) # HH:MM
    last_interaction = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # A customer session is unique to a specific professional's channel
    __table_args__ = (
        UniqueConstraint('tenant_id', 'customer_phone', name='uix_tenant_customer'),
    )

class Appointment(Base):
    __tablename__ = "appointments"

    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    customer_phone = Column(String, nullable=False)
    customer_name = Column(String, nullable=True)
    
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    google_event_id = Column(String, unique=True, nullable=True)
    status = Column(String, default="confirmed")  # confirmed, cancelled
    created_at = Column(DateTime, default=datetime.utcnow)
