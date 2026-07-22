# Implementation Plan: Sender Voice Assets

## Overview

Implement per-Beneficiary voice definitions consumed at generation time and validated at review time. Implementation proceeds bottom-up: domain models → schema extensions → database migration → repository → Personalization_Engine voice integration → Review_Service extension → Analytics_Service segmentation → property-based tests. The implementation language is Python (as specified in the design document).

## Tasks

- [x] 1. Define Voice Asset domain models
  - [x] 1.1 Create `app/core/voice_asset.py` with all enums and dataclasses
    - Define `VoiceRegister`, `SentenceLengthPreference`, `FirstPersonUsage`, `VoiceAssetType` enums
    - Define `ExemplarPassage` dataclass (text, context fields)
    - Define `VoiceAsset` base dataclass with `validate()` method enforcing: 2–3 exemplar passages (50–500 chars each), non-empty vocabulary_avoid
    - Define `WritingStyleAsset(VoiceAsset)` subclass
    - Define `BehavioralProfileAsset` dataclass (interpersonal_style, communication_traits, avoid_impressions)
    - Define `BrandVoiceAsset(VoiceAsset)` subclass with brand_personality, tagline_style
    - Define `VoiceAssetValidationError` and `VoiceAssetNotFoundError` exception classes
    - _Requirements: 1.2_

  - [x] 1.2 Write property test for Voice_Asset template validation (Property 2)
    - **Property 2: Voice_Asset structured template validation**
    - Generate random VoiceAsset instances with varying exemplar counts (0–5), exemplar lengths (0–600 chars), and avoid list sizes (0–10)
    - Verify: validate() returns empty list iff 2–3 exemplars (each 50–500 chars) AND non-empty vocabulary_avoid; returns specific errors otherwise
    - **Validates: Requirements 1.2**

  - [x] 1.3 Write unit tests for Voice_Asset domain models
    - Test enum membership and string values for all voice enums
    - Test VoiceAsset validation edge cases: exactly 2 exemplars, exactly 3, boundary chars 50/500
    - Test BehavioralProfileAsset instantiation
    - Test BrandVoiceAsset with brand_personality field
    - _Requirements: 1.2_

- [x] 2. Extend Schema_Registry with voice asset validation
  - [x] 2.1 Add voice asset types and placement validation to `app/core/schema_registry.py`
    - Add `VOICE_ASSET_TYPES: set[str] = {"writing_style", "behavioral_profile", "brand_voice"}` class constant
    - Implement `_validate_voice_asset_placement()` method enforcing:
      - writing_style and behavioral_profile only on consultant beneficiaries
      - brand_voice only on team beneficiaries
      - behavioral_profile requires writing_style to also be declared
    - Wire `_validate_voice_asset_placement()` into existing `_validate()` method
    - _Requirements: 1.1_

  - [x] 2.2 Add voice assets to beneficiary baseline_assets in `config/schema.yaml`
    - Add `writing_style` and `behavioral_profile` to consultant's baseline_assets list
    - Add `brand_voice` to team's baseline_assets list
    - _Requirements: 1.1_

  - [x] 2.3 Write property test for voice asset placement validation (Property 1)
    - **Property 1: Voice_Asset schema validation rejects invalid placement**
    - Generate random beneficiary configs with voice asset type combinations (valid and invalid placements)
    - Verify: writing_style/behavioral_profile accepted only on consultant, brand_voice only on team, behavioral_profile rejected without writing_style
    - **Validates: Requirements 1.1**

  - [x] 2.4 Write unit tests for Schema_Registry voice asset validation
    - Test brand_voice on consultant raises SchemaValidationError
    - Test writing_style on team raises SchemaValidationError
    - Test behavioral_profile without writing_style raises SchemaValidationError
    - Test valid configurations pass without error
    - _Requirements: 1.1_

- [x] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 4. Create database migration and repository
  - [x] 4.1 Create Alembic migration for voice_assets table and pipeline_records extension
    - Create `voice_assets` table with columns: id (UUID PK), beneficiary_id, asset_type, register, sentence_length, first_person_usage, vocabulary_prefer (JSONB), vocabulary_avoid (JSONB), exemplar_passages (JSONB), interpersonal_style, communication_traits (JSONB), avoid_impressions (JSONB), brand_personality (JSONB), tagline_style, is_active, created_at, updated_at
    - Add UNIQUE constraint on (beneficiary_id, asset_type)
    - Add indexes: idx_voice_assets_beneficiary, idx_voice_assets_type, idx_voice_assets_active (partial WHERE is_active = TRUE)
    - Add `voice_applied BOOLEAN NOT NULL DEFAULT FALSE` column to pipeline_records
    - Add idx_pipeline_records_voice index
    - _Requirements: 1.1, 4.1_

  - [x] 4.2 Create `app/repositories/voice_asset_repo.py` with async CRUD operations
    - Implement `VoiceAssetRepository` class with asyncpg.Pool dependency
    - Implement `get_voice_asset(beneficiary_id, asset_type) -> dict | None` for single asset fetch
    - Implement `get_all_voice_assets(beneficiary_id) -> dict[str, dict | None]` returning all voice assets for a beneficiary
    - Implement `upsert_voice_asset(beneficiary_id, asset_type, asset_data) -> str` for create/update
    - Implement `delete_voice_asset(beneficiary_id, asset_type) -> bool` for soft-delete
    - _Requirements: 1.1, 1.3_

  - [x] 4.3 Write unit tests for VoiceAssetRepository
    - Test get_voice_asset returns None when not found (graceful degradation)
    - Test upsert creates new asset and returns ID
    - Test upsert updates existing asset
    - Test delete_voice_asset soft-deletes (sets is_active=False)
    - Test get_all_voice_assets returns correct structure
    - _Requirements: 1.1, 1.3_

- [x] 5. Implement Personalization_Engine voice integration
  - [x] 5.1 Implement `_build_voice_directives()` method in `app/core/personalization_engine.py`
    - Build combined voice + formality directive text block
    - Include register, sentence_length, first_person_usage from Voice_Asset
    - Apply conflict resolution: Formality_Level for salutation/closing, Voice_Asset for body prose
    - Include behavioral profile traits as tone guidance when present
    - _Requirements: 2.1, 2.2_

  - [x] 5.2 Implement `_build_avoid_prohibitions()` method
    - Format each vocabulary_avoid item as "NEVER: {item}" prohibition line
    - Return multi-line prohibition block prefixed with header
    - _Requirements: 2.3_

  - [x] 5.3 Implement `_build_exemplar_section()` method
    - Format exemplar passages as numbered reference examples with optional context
    - Return formatted exemplar block showing sender's authentic voice
    - _Requirements: 2.1_

  - [x] 5.4 Extend `generate_materials()` to accept and integrate voice assets
    - Add `voice_asset` and `behavioral_profile` optional parameters
    - When voice_asset present: call `_build_voice_directives()`, inject into prompt, set voice_applied=True
    - When voice_asset absent: use current default behavior (Formality only), set voice_applied=False
    - Handle DB timeout gracefully: degrade to no-voice generation
    - _Requirements: 2.1, 2.2, 2.3, 1.3, 4.1_

  - [x] 5.5 Write property test for graceful degradation and voice_applied tagging (Property 3)
    - **Property 3: Graceful degradation and voice_applied tagging**
    - Generate random enrichment data with optional Voice_Asset presence
    - Verify: voice_applied=False when no asset, voice_applied=True when asset present, no errors in either case
    - **Validates: Requirements 1.3, 4.1**

  - [x] 5.6 Write property test for voice content inclusion in generation prompt (Property 4)
    - **Property 4: Voice_Asset content inclusion in generation prompt**
    - Generate random valid VoiceAssets with varied register/vocab/exemplars
    - Verify: generation prompt contains register value, all vocabulary_prefer items, and all exemplar passage texts
    - **Validates: Requirements 2.1**

  - [x] 5.7 Write property test for avoid list prohibitions (Property 5)
    - **Property 5: Avoid list items appear as explicit prohibitions**
    - Generate random non-empty vocabulary_avoid lists
    - Verify: every avoid item appears with "NEVER" prefix in the generation prompt
    - **Validates: Requirements 2.3**

  - [x] 5.8 Write property test for conflict resolution (Property 6)
    - **Property 6: Conflict resolution — Formality wins salutation/closing, Voice wins body**
    - Generate all Formality_Level × VoiceRegister combinations
    - Verify: directive text instructs Formality_Level for salutation/closing and Voice_Asset for body prose
    - **Validates: Requirements 2.2**

  - [x] 5.9 Write unit tests for Personalization_Engine voice methods
    - Test _build_voice_directives produces correctly formatted directive block
    - Test _build_avoid_prohibitions with multiple avoid items
    - Test _build_exemplar_section with context and without context
    - Test C_SUITE + DIRECT register → formal salutation but direct body
    - Test voice_applied tag: True when present, False when absent, False on timeout
    - _Requirements: 2.1, 2.2, 2.3_

- [x] 6. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Implement Review_Service voice extension
  - [x] 7.1 Implement `_build_voice_critique_instructions()` method in `app/core/review_service.py`
    - Build voice compliance check instruction block with register, sentence_length, first_person_usage
    - Include vocabulary_prefer list (flag if absent from draft)
    - Include vocabulary_avoid list (flag if present in draft)
    - Include exemplar passages as reference
    - When behavioral_profile present: add behavioral profile check section with interpersonal_style and avoid_impressions
    - _Requirements: 3.1_

  - [x] 7.2 Extend `_build_fresh_context_prompt()` to include voice reference
    - Add optional `voice_asset` and `behavioral_profile` parameters
    - When voice_asset present: call `_build_voice_critique_instructions()` and append to TONE_STYLE category instructions
    - Instruct reviewer to express mechanical voice fixes as StructuredEdits (reason=STYLE) and subjective concerns as NarrativeFindings (category=TONE_STYLE)
    - _Requirements: 3.1, 3.2_

  - [x] 7.3 Write property test for review critique prompt voice inclusion (Property 7)
    - **Property 7: Review critique prompt includes Voice_Asset when present**
    - Generate random VoiceAssets with varied register, avoid lists, and exemplar passages
    - Verify: critique prompt contains register value, all vocabulary_avoid items, and all exemplar passage texts
    - **Validates: Requirements 3.1**

  - [x] 7.4 Write unit tests for Review_Service voice extension
    - Test _build_voice_critique_instructions with voice_asset only
    - Test _build_voice_critique_instructions with voice_asset + behavioral_profile
    - Test fresh context prompt extends TONE_STYLE category when voice present
    - Test standard prompt when no voice asset (no voice instructions)
    - _Requirements: 3.1, 3.2_

- [x] 8. Implement Analytics_Service voice segmentation
  - [x] 8.1 Add `VoiceSegmentedFunnel` dataclass to `app/core/analytics_service.py`
    - Define frozen dataclass with: voice_applied_funnel, no_voice_funnel, voice_applied_reply_rate, no_voice_reply_rate, lift_percentage, is_statistically_significant, sample_size_voice, sample_size_no_voice
    - _Requirements: 4.2_

  - [x] 8.2 Implement `compute_voice_segmented_funnel()` method on AnalyticsService
    - Compute separate funnels for voice_applied=True and voice_applied=False subsets
    - Calculate reply rates: voice_replies/voice_sends and no_voice_replies/no_voice_sends
    - Compute lift percentage: (voice_rr - no_voice_rr) / no_voice_rr × 100
    - Implement z-test for statistical significance at 90% confidence with minimum sample size check
    - _Requirements: 4.2_

  - [x] 8.3 Write property test for analytics voice segmentation (Property 8)
    - **Property 8: Analytics voice segmentation correctness**
    - Generate random send/reply counts for voice and no-voice segments
    - Verify: voice_applied_reply_rate = voice_replies/voice_sends, no_voice_reply_rate = no_voice_replies/no_voice_sends, each computed independently
    - **Validates: Requirements 4.2**

  - [x] 8.4 Write unit tests for voice segmented funnel
    - Test lift calculation with known values
    - Test statistical significance with large sample (significant) and small sample (not significant)
    - Test edge cases: zero sends (0.0 rate), equal rates (lift = 0), no-voice rate zero (lift = None)
    - _Requirements: 4.2_

- [x] 9. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 10. Integration and wiring
  - [x] 10.1 Wire voice asset fetching into the prepare pipeline
    - Before calling PersonalizationEngine.generate_materials(), fetch voice assets via VoiceAssetRepository
    - Pass voice_asset and behavioral_profile to generate_materials()
    - Pass voice_asset and behavioral_profile to ReviewService._build_fresh_context_prompt() during review phase
    - Persist voice_applied tag on the pipeline_record after generation
    - _Requirements: 2.1, 3.1, 4.1_

  - [x] 10.2 Add Dashboard suggestion for missing voice assets
    - In the Understand stage, when no Voice_Asset is configured for a beneficiary, display a one-time suggestion to create the asset
    - Suggestion is non-blocking (voice is opt-in)
    - _Requirements: 1.3_

  - [x] 10.3 Write integration tests for voice generation end-to-end
    - Test: VoiceAsset in DB → PersonalizationEngine → verify prompt contains voice directives and voice_applied=True on result
    - Test: No VoiceAsset → PersonalizationEngine → verify default behavior and voice_applied=False
    - Test: VoiceAsset present → ReviewService → verify TONE_STYLE critique includes voice compliance check
    - _Requirements: 2.1, 3.1, 4.1_

  - [x] 10.4 Write integration test for analytics segmentation
    - Generate mixed voice/no-voice pipeline_records
    - Call compute_voice_segmented_funnel and verify correct segmentation
    - Verify Reports stage can display segmented data
    - _Requirements: 4.2_

- [x] 11. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate the 8 universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The implementation language is Python (as specified in the design document)
- Integration tests use mocked database and LLM_Router to avoid external calls during testing
- The system must gracefully degrade when no Voice_Asset is configured — this is tested in Property 3

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1"] },
    { "id": 1, "tasks": ["1.2", "1.3", "2.1"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4"] },
    { "id": 3, "tasks": ["4.1"] },
    { "id": 4, "tasks": ["4.2", "4.3"] },
    { "id": 5, "tasks": ["5.1", "5.2", "5.3"] },
    { "id": 6, "tasks": ["5.4"] },
    { "id": 7, "tasks": ["5.5", "5.6", "5.7", "5.8", "5.9"] },
    { "id": 8, "tasks": ["7.1"] },
    { "id": 9, "tasks": ["7.2", "7.3", "7.4"] },
    { "id": 10, "tasks": ["8.1"] },
    { "id": 11, "tasks": ["8.2", "8.3", "8.4"] },
    { "id": 12, "tasks": ["10.1", "10.2"] },
    { "id": 13, "tasks": ["10.3", "10.4"] }
  ]
}
```
