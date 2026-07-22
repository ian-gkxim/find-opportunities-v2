"""Repository for Voice Asset persistence.

Handles CRUD operations for voice assets (writing_style, behavioral_profile,
brand_voice) using raw SQL via SQLAlchemy text() queries.

Requirements: 1.1, 1.3
"""

import json
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)


class VoiceAssetRepository:
    """Async PostgreSQL repository for Voice_Asset CRUD operations.

    Uses raw SQL with text() queries following the same async session
    pattern as ReviewRepository and GroundingRepository.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._session_factory = session_factory

    async def get_voice_asset(
        self, beneficiary_id: str, asset_type: str
    ) -> dict | None:
        """Fetch the active voice asset for a beneficiary.

        Returns None if no asset configured (graceful degradation path).

        Args:
            beneficiary_id: The beneficiary's identifier.
            asset_type: One of writing_style, behavioral_profile, brand_voice.

        Returns:
            Dict with asset data if found and active, None otherwise.
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, beneficiary_id, asset_type, register,
                       sentence_length, first_person_usage,
                       vocabulary_prefer, vocabulary_avoid,
                       exemplar_passages, interpersonal_style,
                       communication_traits, avoid_impressions,
                       brand_personality, tagline_style,
                       is_active, created_at, updated_at
                FROM voice_assets
                WHERE beneficiary_id = :beneficiary_id
                  AND asset_type = :asset_type
                  AND is_active = TRUE
            """)
            result = await session.execute(
                stmt,
                {
                    "beneficiary_id": beneficiary_id,
                    "asset_type": asset_type,
                },
            )
            row = result.fetchone()

            if row is None:
                return None

            return _row_to_dict(row)

    async def get_all_voice_assets(
        self, beneficiary_id: str
    ) -> dict[str, dict | None]:
        """Fetch all voice-related assets for a beneficiary.

        Returns a dict keyed by asset type with the asset data or None
        for each type that doesn't exist.

        Args:
            beneficiary_id: The beneficiary's identifier.

        Returns:
            Dict: {
                "writing_style": dict | None,
                "behavioral_profile": dict | None,
                "brand_voice": dict | None
            }
        """
        async with self._session_factory() as session:
            stmt = text("""
                SELECT id, beneficiary_id, asset_type, register,
                       sentence_length, first_person_usage,
                       vocabulary_prefer, vocabulary_avoid,
                       exemplar_passages, interpersonal_style,
                       communication_traits, avoid_impressions,
                       brand_personality, tagline_style,
                       is_active, created_at, updated_at
                FROM voice_assets
                WHERE beneficiary_id = :beneficiary_id
                  AND is_active = TRUE
            """)
            result = await session.execute(
                stmt,
                {"beneficiary_id": beneficiary_id},
            )
            rows = result.fetchall()

            assets: dict[str, dict | None] = {
                "writing_style": None,
                "behavioral_profile": None,
                "brand_voice": None,
            }

            for row in rows:
                asset_dict = _row_to_dict(row)
                asset_type = asset_dict["asset_type"]
                if asset_type in assets:
                    assets[asset_type] = asset_dict

            return assets

    async def upsert_voice_asset(
        self, beneficiary_id: str, asset_type: str, asset_data: dict
    ) -> str:
        """Create or update a voice asset. Returns asset ID.

        If an asset already exists for (beneficiary_id, asset_type),
        it is updated. Otherwise a new asset is created.

        Args:
            beneficiary_id: The beneficiary's identifier.
            asset_type: One of writing_style, behavioral_profile, brand_voice.
            asset_data: Dict with asset fields (register, sentence_length, etc.)

        Returns:
            The UUID string of the created/updated asset.
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            # Check if asset already exists (including inactive)
            check_stmt = text("""
                SELECT id FROM voice_assets
                WHERE beneficiary_id = :beneficiary_id
                  AND asset_type = :asset_type
            """)
            result = await session.execute(
                check_stmt,
                {
                    "beneficiary_id": beneficiary_id,
                    "asset_type": asset_type,
                },
            )
            existing = result.fetchone()

            if existing:
                # Update existing asset
                asset_id = str(existing[0])
                update_stmt = text("""
                    UPDATE voice_assets
                    SET register = :register,
                        sentence_length = :sentence_length,
                        first_person_usage = :first_person_usage,
                        vocabulary_prefer = :vocabulary_prefer,
                        vocabulary_avoid = :vocabulary_avoid,
                        exemplar_passages = :exemplar_passages,
                        interpersonal_style = :interpersonal_style,
                        communication_traits = :communication_traits,
                        avoid_impressions = :avoid_impressions,
                        brand_personality = :brand_personality,
                        tagline_style = :tagline_style,
                        is_active = TRUE,
                        updated_at = :updated_at
                    WHERE id = :id
                """)
                await session.execute(
                    update_stmt,
                    {
                        "id": asset_id,
                        "register": asset_data.get("register", "direct"),
                        "sentence_length": asset_data.get("sentence_length", "medium"),
                        "first_person_usage": asset_data.get("first_person_usage", "moderate"),
                        "vocabulary_prefer": json.dumps(asset_data.get("vocabulary_prefer", [])),
                        "vocabulary_avoid": json.dumps(asset_data.get("vocabulary_avoid", [])),
                        "exemplar_passages": json.dumps(asset_data.get("exemplar_passages", [])),
                        "interpersonal_style": asset_data.get("interpersonal_style"),
                        "communication_traits": json.dumps(asset_data.get("communication_traits")) if asset_data.get("communication_traits") else None,
                        "avoid_impressions": json.dumps(asset_data.get("avoid_impressions")) if asset_data.get("avoid_impressions") else None,
                        "brand_personality": json.dumps(asset_data.get("brand_personality")) if asset_data.get("brand_personality") else None,
                        "tagline_style": asset_data.get("tagline_style"),
                        "updated_at": now,
                    },
                )
            else:
                # Insert new asset
                asset_id = str(uuid.uuid4())
                insert_stmt = text("""
                    INSERT INTO voice_assets (
                        id, beneficiary_id, asset_type, register,
                        sentence_length, first_person_usage,
                        vocabulary_prefer, vocabulary_avoid,
                        exemplar_passages, interpersonal_style,
                        communication_traits, avoid_impressions,
                        brand_personality, tagline_style,
                        is_active, created_at, updated_at
                    ) VALUES (
                        :id, :beneficiary_id, :asset_type, :register,
                        :sentence_length, :first_person_usage,
                        :vocabulary_prefer, :vocabulary_avoid,
                        :exemplar_passages, :interpersonal_style,
                        :communication_traits, :avoid_impressions,
                        :brand_personality, :tagline_style,
                        TRUE, :created_at, :updated_at
                    )
                """)
                await session.execute(
                    insert_stmt,
                    {
                        "id": asset_id,
                        "beneficiary_id": beneficiary_id,
                        "asset_type": asset_type,
                        "register": asset_data.get("register", "direct"),
                        "sentence_length": asset_data.get("sentence_length", "medium"),
                        "first_person_usage": asset_data.get("first_person_usage", "moderate"),
                        "vocabulary_prefer": json.dumps(asset_data.get("vocabulary_prefer", [])),
                        "vocabulary_avoid": json.dumps(asset_data.get("vocabulary_avoid", [])),
                        "exemplar_passages": json.dumps(asset_data.get("exemplar_passages", [])),
                        "interpersonal_style": asset_data.get("interpersonal_style"),
                        "communication_traits": json.dumps(asset_data.get("communication_traits")) if asset_data.get("communication_traits") else None,
                        "avoid_impressions": json.dumps(asset_data.get("avoid_impressions")) if asset_data.get("avoid_impressions") else None,
                        "brand_personality": json.dumps(asset_data.get("brand_personality")) if asset_data.get("brand_personality") else None,
                        "tagline_style": asset_data.get("tagline_style"),
                        "created_at": now,
                        "updated_at": now,
                    },
                )

            await session.commit()

        logger.debug(
            "Upserted voice asset %s for beneficiary %s (type=%s)",
            asset_id,
            beneficiary_id,
            asset_type,
        )
        return asset_id

    async def delete_voice_asset(
        self, beneficiary_id: str, asset_type: str
    ) -> bool:
        """Soft-delete a voice asset (sets is_active=False).

        Args:
            beneficiary_id: The beneficiary's identifier.
            asset_type: One of writing_style, behavioral_profile, brand_voice.

        Returns:
            True if an active asset was found and soft-deleted, False otherwise.
        """
        now = datetime.now(timezone.utc)

        async with self._session_factory() as session:
            stmt = text("""
                UPDATE voice_assets
                SET is_active = FALSE, updated_at = :updated_at
                WHERE beneficiary_id = :beneficiary_id
                  AND asset_type = :asset_type
                  AND is_active = TRUE
            """)
            result = await session.execute(
                stmt,
                {
                    "beneficiary_id": beneficiary_id,
                    "asset_type": asset_type,
                    "updated_at": now,
                },
            )
            await session.commit()

            deleted = result.rowcount > 0

        if deleted:
            logger.debug(
                "Soft-deleted voice asset for beneficiary %s (type=%s)",
                beneficiary_id,
                asset_type,
            )
        else:
            logger.debug(
                "No active voice asset found to delete for beneficiary %s (type=%s)",
                beneficiary_id,
                asset_type,
            )

        return deleted


# ─── Helper functions ─────────────────────────────────────────────────────────


def _row_to_dict(row) -> dict:
    """Convert a database row tuple to a voice asset dict."""
    return {
        "id": str(row[0]),
        "beneficiary_id": str(row[1]),
        "asset_type": str(row[2]),
        "register": str(row[3]),
        "sentence_length": str(row[4]),
        "first_person_usage": str(row[5]),
        "vocabulary_prefer": row[6] if isinstance(row[6], list) else json.loads(row[6]) if row[6] else [],
        "vocabulary_avoid": row[7] if isinstance(row[7], list) else json.loads(row[7]) if row[7] else [],
        "exemplar_passages": row[8] if isinstance(row[8], list) else json.loads(row[8]) if row[8] else [],
        "interpersonal_style": row[9],
        "communication_traits": row[10] if isinstance(row[10], list) else json.loads(row[10]) if row[10] else None,
        "avoid_impressions": row[11] if isinstance(row[11], list) else json.loads(row[11]) if row[11] else None,
        "brand_personality": row[12] if isinstance(row[12], list) else json.loads(row[12]) if row[12] else None,
        "tagline_style": row[13],
        "is_active": row[14],
        "created_at": row[15],
        "updated_at": row[16],
    }
