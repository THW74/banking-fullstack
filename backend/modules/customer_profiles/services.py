import uuid
from datetime import date, datetime, timezone
from fastapi import HTTPException, status
from sqlmodel import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CustomerProfile
from .enums import KycStatusEnum, EmploymentStatusEnum
from .schemas import CustomerProfileCreateSchema, CustomerProfileUpdateSchema


class CustomerProfileService:
    async def get_by_user_id(self, db: AsyncSession, user_id: uuid.UUID) -> CustomerProfile | None:
        statement = select(CustomerProfile).where(CustomerProfile.user_id == user_id)
        result = await db.execute(statement)
        return result.scalar_one_or_none()

    async def create_profile(
        self, db: AsyncSession, user_id: uuid.UUID, profile_in: CustomerProfileCreateSchema
    ) -> CustomerProfile:
        existing = await self.get_by_user_id(db, user_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Profile already exists for this user"
            )

        db_profile = CustomerProfile(
            user_id=user_id,
            phone_number=profile_in.phone_number,
            kyc_status=KycStatusEnum.DRAFT,
        )
        db.add(db_profile)
        await db.commit()
        await db.refresh(db_profile)
        return db_profile

    async def update_profile(
        self, db: AsyncSession, user_id: uuid.UUID, profile_in: CustomerProfileUpdateSchema
    ) -> CustomerProfile:
        profile = await self.get_by_user_id(db, user_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )

        if profile.kyc_status not in {KycStatusEnum.DRAFT, KycStatusEnum.REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft or rejected profiles can be updated"
            )

        # Update fields
        update_data = profile_in.model_dump(exclude_unset=True)
        for key, value in update_data.items():
            setattr(profile, key, value)

        profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    def validate_submission(self, profile: CustomerProfile) -> None:
        errors = []

        # Core personal details
        if not profile.title: errors.append("title is required")
        if not profile.gender: errors.append("gender is required")
        if not profile.date_of_birth: errors.append("date_of_birth is required")
        if not profile.country_of_birth: errors.append("country_of_birth is required")
        if not profile.place_of_birth: errors.append("place_of_birth is required")
        if not profile.marital_status: errors.append("marital_status is required")
        if not profile.nationality: errors.append("nationality is required")

        # Identity documents validation
        if not profile.identification_type: errors.append("identification_type is required")
        if not profile.identification_number: errors.append("identification_number is required")
        if not profile.id_issue_date: errors.append("id_issue_date is required")
        if not profile.id_expiry_date: errors.append("id_expiry_date is required")

        # Dates validation
        if profile.id_issue_date and profile.id_issue_date >= date.today():
            errors.append("id_issue_date must be in the past")
        if profile.id_expiry_date and profile.id_expiry_date <= date.today():
            errors.append("identification document is expired")
        if profile.id_issue_date and profile.id_expiry_date and profile.id_expiry_date <= profile.id_issue_date:
            errors.append("id_expiry_date must be after id_issue_date")

        # Contact info
        if not profile.phone_number: errors.append("phone_number is required")
        if not profile.address: errors.append("address is required")
        if not profile.city: errors.append("city is required")
        if not profile.country: errors.append("country is required")

        # Employment details
        if not profile.employment_status:
            errors.append("employment_status is required")
        elif profile.employment_status in {EmploymentStatusEnum.EMPLOYED, EmploymentStatusEnum.SELF_EMPLOYED}:
            if not profile.employer_name: errors.append("employer_name is required")
            if not profile.employer_address: errors.append("employer_address is required")
            if not profile.employer_city: errors.append("employer_city is required")
            if not profile.employer_country: errors.append("employer_country is required")
            if profile.annual_income is None: errors.append("annual_income is required")
            if not profile.date_of_employment: errors.append("date_of_employment is required")

        # Image URLs (id_photo_url is required for submission)
        if not profile.id_photo_url:
            errors.append("id_photo_url is required")

        if errors:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Incomplete KYC data: {', '.join(errors)}"
            )

    async def submit_profile(self, db: AsyncSession, user_id: uuid.UUID) -> CustomerProfile:
        profile = await self.get_by_user_id(db, user_id)
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )

        if profile.kyc_status not in {KycStatusEnum.DRAFT, KycStatusEnum.REJECTED}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only draft or rejected profiles can be submitted"
            )

        self.validate_submission(profile)

        # Transition status and reset review parameters on submit/resubmit
        profile.kyc_status = KycStatusEnum.SUBMITTED
        profile.submitted_at = datetime.now(timezone.utc).replace(tzinfo=None)
        profile.rejection_reason = None
        profile.reviewed_at = None
        profile.reviewed_by_user_id = None
        profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(profile)
        await db.commit()
        await db.refresh(profile)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            await notification_service.create_notification(
                db,
                user_id=profile.user_id,
                title="KYC Profile Submitted",
                message="Your KYC profile has been submitted for review.",
                notification_type=NotificationTypeEnum.KYC,
                source_metadata={"profile_id": str(profile.id)},
            )
        except Exception:
            await db.rollback()

        await db.refresh(profile)
        return profile

    async def list_profiles_for_review(
        self, db: AsyncSession, kyc_status: KycStatusEnum | None = None, limit: int = 50, offset: int = 0
    ) -> list[CustomerProfile]:
        statement = select(CustomerProfile)
        if kyc_status:
            statement = statement.where(CustomerProfile.kyc_status == kyc_status)
        statement = statement.order_by(desc(CustomerProfile.submitted_at).nulls_last())
        statement = statement.offset(offset).limit(limit)
        result = await db.execute(statement)
        return list(result.scalars().all())

    async def get_profile_by_id_for_admin(self, db: AsyncSession, profile_id: uuid.UUID) -> CustomerProfile:
        statement = select(CustomerProfile).where(CustomerProfile.id == profile_id)
        result = await db.execute(statement)
        profile = result.scalar_one_or_none()
        if not profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Profile not found"
            )
        return profile

    async def mark_under_review(self, db: AsyncSession, profile_id: uuid.UUID, reviewer_id: uuid.UUID) -> CustomerProfile:
        profile = await self.get_profile_by_id_for_admin(db, profile_id)
        if profile.kyc_status != KycStatusEnum.SUBMITTED:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only submitted profiles can be transitioned to under review"
            )

        profile.kyc_status = KycStatusEnum.UNDER_REVIEW
        profile.reviewed_by_user_id = reviewer_id
        profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(profile)
        await db.commit()
        await db.refresh(profile)
        return profile

    async def approve_profile(self, db: AsyncSession, profile_id: uuid.UUID, reviewer_id: uuid.UUID) -> CustomerProfile:
        profile = await self.get_profile_by_id_for_admin(db, profile_id)
        if profile.kyc_status not in {KycStatusEnum.SUBMITTED, KycStatusEnum.UNDER_REVIEW}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only submitted or under review profiles can be approved"
            )

        profile.kyc_status = KycStatusEnum.APPROVED
        profile.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        profile.reviewed_by_user_id = reviewer_id
        profile.rejection_reason = None
        profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(profile)
        await db.commit()
        await db.refresh(profile)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            await notification_service.create_notification(
                db,
                user_id=profile.user_id,
                title="KYC Profile Approved",
                message="Your KYC profile has been successfully approved.",
                notification_type=NotificationTypeEnum.KYC,
                source_metadata={"profile_id": str(profile.id)},
            )
        except Exception:
            await db.rollback()

        await db.refresh(profile)
        return profile

    async def reject_profile(
        self, db: AsyncSession, profile_id: uuid.UUID, reviewer_id: uuid.UUID, rejection_reason: str
    ) -> CustomerProfile:
        profile = await self.get_profile_by_id_for_admin(db, profile_id)
        if profile.kyc_status not in {KycStatusEnum.SUBMITTED, KycStatusEnum.UNDER_REVIEW}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Only submitted or under review profiles can be rejected"
            )

        if not rejection_reason or not rejection_reason.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Rejection reason is required"
            )

        profile.kyc_status = KycStatusEnum.REJECTED
        profile.rejection_reason = rejection_reason.strip()
        profile.reviewed_at = datetime.now(timezone.utc).replace(tzinfo=None)
        profile.reviewed_by_user_id = reviewer_id
        profile.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)

        db.add(profile)
        await db.commit()
        await db.refresh(profile)

        try:
            from modules.notifications.services import notification_service
            from modules.notifications.enums import NotificationTypeEnum
            await notification_service.create_notification(
                db,
                user_id=profile.user_id,
                title="KYC Profile Rejected",
                message=f"Your KYC profile has been rejected. Reason: {profile.rejection_reason}",
                notification_type=NotificationTypeEnum.KYC,
                source_metadata={"profile_id": str(profile.id), "rejection_reason": profile.rejection_reason},
            )
        except Exception:
            await db.rollback()

        await db.refresh(profile)
        return profile


customer_profile_service = CustomerProfileService()
