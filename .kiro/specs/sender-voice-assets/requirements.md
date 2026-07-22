# Requirements Document

## Introduction

Sender Voice Assets give every Beneficiary a persistent voice definition — a writing-style guide and an optional behavioral profile for Consultants, and a brand-voice document for the Team — that the Personalization_Engine consumes at generation time and the Review_Service checks at critique time. The current engine adapts tone to the recipient's seniority but has no concept of the sender's natural register, so materials generated for different consultants sound interchangeable. Cold outreach performance depends on sounding like a specific person; this feature makes voice a first-class, schema-declared asset. Priority: P3.

## Glossary

- **Voice_Asset**: A profile asset defining how a Beneficiary writes: preferred register, sentence rhythm, vocabulary preferences and prohibitions, and phrases or constructions to avoid
- **Writing_Style_Asset**: The Voice_Asset type for an individual Consultant
- **Behavioral_Profile_Asset**: An optional Consultant asset describing working style and interpersonal register (e.g. collaborative vs. driving), used to keep material tone consistent with how the person actually presents
- **Brand_Voice_Asset**: The Voice_Asset type for the Team beneficiary, defining the firm's written identity
- **Formality_Level**: The recipient-derived tone dimension already computed by the Personalization_Engine from contact seniority
- Existing terms (Personalization_Engine, Review_Service, Beneficiary, baseline_assets, Schema_Registry) are as defined in the system-redesign-v2 and review-critique-loop requirements documents

## Requirements

### Requirement 1: Schema Declaration

**User Story:** As a system maintainer, I want voice assets declared per beneficiary in the schema, so that adding voice support is a configuration change.

#### Acceptance Criteria

1. THE Schema_Registry SHALL support declaring a `writing_style` asset and an optional `behavioral_profile` asset in the Consultant beneficiary's baseline_assets, and a `brand_voice` asset in the Team beneficiary's baseline_assets
2. THE System SHALL provide a structured template for each Voice_Asset type covering at minimum: register (e.g. direct, warm, formal), sentence-length preference, first-person usage, vocabulary to prefer, vocabulary and constructions to avoid, and 2–3 short exemplar passages written in the Beneficiary's authentic voice
3. IF a Voice_Asset is absent for a Beneficiary, THEN THE Personalization_Engine SHALL generate materials using current default behavior without error, and THE Dashboard SHALL display a one-time suggestion in the Understand stage to create the asset

### Requirement 2: Generation-Time Consumption

**User Story:** As a Consultant user, I want materials generated in my voice, so that outreach sent in my name sounds like me and not like a template.

#### Acceptance Criteria

1. WHEN building a generation prompt, THE Personalization_Engine SHALL include the Beneficiary's Voice_Asset content (and Behavioral_Profile_Asset where present) in the prompt context for all material types
2. THE Personalization_Engine SHALL combine tone dimensions as follows: the recipient's Formality_Level sets the formality of the material, while the sender's Voice_Asset sets register, rhythm, and vocabulary; WHERE the two conflict on a specific choice, THE Personalization_Engine SHALL apply the Formality_Level for salutation and closing conventions and the Voice_Asset for body prose
3. THE Personalization_Engine SHALL include the Voice_Asset's "avoid" list as explicit prohibitions in the generation prompt

### Requirement 3: Review-Time Voice Check

**User Story:** As a Consultant user, I want voice mismatches caught in review, so that a draft that doesn't sound like me is flagged before I read it.

#### Acceptance Criteria

1. WHERE a Voice_Asset exists for the Beneficiary, THE Review_Service SHALL include the Voice_Asset in the reviewer's reference context and SHALL extend the tone/style critique category to explicitly check the draft's voice against the Voice_Asset, including any Behavioral_Profile_Asset register described (e.g. flagging a combative, solo-hero tone for a collaborative profile, or over-hedged apologetic phrasing for a direct profile)
2. WHEN the reviewer finds a voice mismatch, THE Review_Service SHALL express the finding as Structured_Edits where the fix is a mechanical rephrase, and as a Narrative_Finding in the tone/style category otherwise

### Requirement 4: A/B Observability

**User Story:** As a Team user, I want to see whether voice-tuned materials perform better, so that investment in voice assets is justified by reply-rate data.

#### Acceptance Criteria

1. THE System SHALL tag each generated material with a `voice_applied` boolean indicating whether a Voice_Asset was present at generation time
2. THE Analytics_Service SHALL segment sequence reply rates by the `voice_applied` tag in the conversion funnel reporting, displayable in the Reports stage
