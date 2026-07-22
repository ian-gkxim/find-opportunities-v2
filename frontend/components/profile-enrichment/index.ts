/**
 * Profile Enrichment UI Components
 *
 * Components for the Internal Profile Enrichment feature,
 * displayed in the Understand stage of the Dashboard.
 */

export { ProposalReview } from "./ProposalReview";
export type {
  CompetencyProposal,
  ProposalStatus,
  ProposalConfidence,
} from "./ProposalReview";

export { useProposalNotifications } from "./useProposalNotifications";
export type {
  NewProposalsEvent,
  SourceFailureEvent,
} from "./useProposalNotifications";
