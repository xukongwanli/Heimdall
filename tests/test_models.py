import uuid
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.app.models import Base, Listing


DB_URL = "postgresql://localhost/heimdall"
engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)


def setup_module():
    Base.metadata.create_all(engine)


def teardown_module():
    Base.metadata.drop_all(engine)


def test_create_listing():
    session = Session()
    try:
        listing = Listing(
            id=uuid.uuid4(),
            source="zillow",
            listing_type="buy",
            address="123 main street",
            city="austin",
            country="US",
            region="TX",
            postal_code="78701",
            price=450000,
            sqft=1800,
            price_per_sqft=250.00,
            source_url="https://zillow.com/123",
            published_at=datetime.now(timezone.utc),
            crawled_at=datetime.now(timezone.utc),
        )
        session.add(listing)
        session.commit()

        result = session.query(Listing).filter_by(address="123 main street").first()
        assert result is not None
        assert result.price == 450000
        assert result.source == "zillow"
    finally:
        session.rollback()
        session.close()


def test_listing_unique_constraint():
    """Duplicate (source, address, listing_type) should raise."""
    session = Session()
    try:
        now = datetime.now(timezone.utc)
        l1 = Listing(
            id=uuid.uuid4(), source="zillow", listing_type="buy",
            address="456 oak avenue", city="austin", country="US",
            region="TX", postal_code="78701", price=300000,
            source_url="https://zillow.com/456",
            published_at=now, crawled_at=now,
        )
        l2 = Listing(
            id=uuid.uuid4(), source="zillow", listing_type="buy",
            address="456 oak avenue", city="dallas", country="US",
            region="TX", postal_code="75201", price=350000,
            source_url="https://zillow.com/456b",
            published_at=now, crawled_at=now,
        )
        session.add(l1)
        session.commit()
        session.add(l2)
        from sqlalchemy.exc import IntegrityError
        import pytest
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_listing_nullable_sqft():
    """Listings without sqft should store with NULL price_per_sqft."""
    session = Session()
    try:
        listing = Listing(
            id=uuid.uuid4(), source="realtor", listing_type="rent",
            address="789 elm street", city="houston", country="US",
            region="TX", postal_code="77001", price=2000,
            sqft=None, price_per_sqft=None,
            source_url="https://realtor.com/789",
            published_at=datetime.now(timezone.utc),
            crawled_at=datetime.now(timezone.utc),
        )
        session.add(listing)
        session.commit()

        result = session.query(Listing).filter_by(address="789 elm street").first()
        assert result.sqft is None
        assert result.price_per_sqft is None
    finally:
        session.rollback()
        session.close()
