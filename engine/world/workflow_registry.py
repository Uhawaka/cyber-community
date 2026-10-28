"""Closed workflow operations and policies, including the community loop."""

WORKFLOW_SCHEMA_VERSION = "world-workflow/v1alpha1"
PRESENTATION_WORKFLOW_SCHEMA_VERSION = "world-workflow/v1alpha3"
WORKFLOW_OPS = {
    "genesis": ("load_world", "load_locations", "load_characters", "load_resources", "load_passages"),
    "evolution": (
        "environment_update", "incident_scheduler", "actor_windows", "scene_turns",
        "scheme_progress", "memory_consolidation", "phase_check", "community_runtime",
    ),
    "intervention": ("incident", "user_gate", "fate"),
    "presentation": ("source_filter", "curate", "plan", "render", "validate", "publish"),
}
WORKFLOW_POLICIES = {
    "genesis": frozenset(),
    "evolution": frozenset({
        "need_decay", "action_budget", "opportunity_budget", "incident_budget",
        "memory_budget", "max_catchup_ticks", "hot_character_ids",
        "hot_location_ids", "phase_predicates",
    }),
    "intervention": frozenset({
        "avatar_offline_policy", "allow_incidents", "allow_gates", "allow_fate",
    }),
    "presentation": frozenset({
        "unpresented_event_threshold", "critical_event_threshold", "renderer",
        "audience_default", "episode", "style", "editorial_pipeline",
    }),
}
