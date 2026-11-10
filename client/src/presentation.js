/** User-facing activity names; raw engine identifiers remain available in diagnostic disclosures. */
const activities={
 project:'project',source_import:'source-import',source_register:'source-register',plan:'plan',run_created:'run',
 source_processed:'worker',acquisition_checkpoint:'worker',acquisition_resumed:'resume',
 collector_probed:'collector-probe',search_started:'search',search_completed:'search',search_failed:'search',
 source_image_archived:'source-image',evidence_selected:'evidence',context_prepared:'context',
 analysis_submitted:'analysis',review_requested:'review',review_completed:'review',review_failed:'review',
 semantic_verification_submitted:'verification',delivery_prepared:'deliver',delivery_published:'deliver',delivery_failed:'deliver',
}

/** Return the locale key for a recorded activity without inventing a result. */
export function activityKey(kind){return 'action_'+(activities[kind]??kind)}
