"""Core evolution-tool declarations for the Continual Harness.

This module is the single source of truth for the framework's evolution tools:
memory, skills, subagents, the evolve_harness reflection pass, and task
planning. Benchmarks compose these (via :mod:`continual_harness.tools.families`)
with their own ``bash`` / ``task_complete`` tool *descriptions* — they do not
redefine the evolution tools.

Tools use the Gemini-style declaration format; ``continual_harness.llm`` converts
them to OpenAI function-calling format for litellm.
"""

# --- Memory ---------------------------------------------------------------

SAVE_MEMORY_TOOL = {
    "name": "save_memory",
    "description": (
        "Save a lesson or observation to long-term memory for use in future tasks. "
        "Use this to record insights, patterns, or strategies discovered during this task."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "title": {
                "type_": "STRING",
                "description": "Short title for the memory entry",
            },
            "content": {
                "type_": "STRING",
                "description": "The lesson, observation, or strategy to remember",
            },
        },
        "required": ["title", "content"],
    },
}

READ_MEMORY_TOOL = {
    "name": "read_memory",
    "description": (
        "Fetch one memory entry in full (title + content) by its ID. Get the ID from "
        "list_memory, which lists every saved entry. Use this to read the details of a "
        "specific memory you've identified as relevant."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "memory_id": {
                "type_": "STRING",
                "description": "ID of the memory entry to read in full (e.g., 'mem_0001')",
            },
        },
        "required": ["memory_id"],
    },
}

LIST_MEMORY_TOOL = {
    "name": "list_memory",
    "description": (
        "List ALL your saved memories as `[id] title` lines (titles only, not full content). "
        "Takes no arguments and returns every entry — there is no query or ranking, so you see "
        "the complete set of prior knowledge you have. Do this at the start of a task, then "
        "read_memory the ones that look useful to see their full content."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {},
    },
}

# --- Skills ---------------------------------------------------------------

SAVE_SKILL_TOOL = {
    "name": "save_skill",
    "description": (
        "Save a reusable skill — a learned procedure for a recurring kind of work — for "
        "future tasks. A skill primarily captures the WORKFLOW: the ordered steps, the order "
        "that works, the pitfalls to avoid. It may ALSO include an executable code snippet when "
        "part of the procedure is a clean, parameterizable command sequence. Retrieve a saved "
        "skill later with get_skill. Use this when you work out a multi-step approach you expect "
        "to repeat."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "name": {
                "type_": "STRING",
                "description": "Short descriptive name for the skill (e.g., 'fix_flaky_timing_tests')",
            },
            "summary": {
                "type_": "STRING",
                "description": (
                    "OPTIONAL. A one-line gist of what this skill is for and when to use it "
                    "(e.g., 'Safely apply data-retention purge migrations, wave by wave'). This "
                    "is what list_skills shows so future-you can tell at a glance whether the "
                    "skill applies; the full workflow stays in `description` and is fetched with "
                    "get_skill. Keep it to one sentence."
                ),
            },
            "description": {
                "type_": "STRING",
                "description": (
                    "The workflow: what the skill is for, when to use it, and the ordered steps "
                    "to follow (including any gotchas). This is the core of the skill — make it "
                    "specific enough that future-you can follow it."
                ),
            },
            "code": {
                "type_": "STRING",
                "description": (
                    "OPTIONAL. An executable bash snippet for the part of the workflow that is a "
                    "clean reusable command sequence (use $1, $2, … for arguments). Omit it when "
                    "the skill is judgment/workflow guidance rather than a fixed command."
                ),
            },
        },
        "required": ["name", "description"],
    },
}

GET_SKILL_TOOL = {
    "name": "get_skill",
    "description": (
        "Retrieve a previously saved skill by ID: returns its workflow (the steps to follow) "
        "and its executable code snippet if it has one. This does NOT run anything — read the "
        "workflow and follow it, and if there's code, review it and then run it yourself with "
        "bash (substituting any arguments). Use list_skills (or the skill library in your system "
        "prompt) to find skill IDs."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "skill_id": {
                "type_": "STRING",
                "description": "ID of the skill to retrieve (e.g., 'skill_0001')",
            },
        },
        "required": ["skill_id"],
    },
}

LIST_SKILLS_TOOL = {
    "name": "list_skills",
    "description": (
        "List all saved skills with their IDs, names, and one-line summaries. "
        "Use this to discover what reusable workflows are available before "
        "starting a task; it shows only the gist of each skill, not the full "
        "steps. Retrieve a skill's full workflow (and code) with get_skill."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {},
        "required": [],
    },
}

# --- Subagents ------------------------------------------------------------

SPAWN_SUBAGENT_TOOL = {
    "name": "spawn_subagent",
    "description": (
        "Spawn a subagent of a registered type to handle a sub-task. "
        "The subagent runs independently with access to bash, memory, and skills. "
        "It can ask you for clarification if needed. "
        "Use list_subagents to see available types. "
        "Use register_subagent to create new types."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "type": {
                "type_": "STRING",
                "description": "The subagent type name (e.g., 'explore', 'analyze_file', 'investigate'). Must be a registered type from list_subagents.",
            },
            "query": {
                "type_": "STRING",
                "description": "The specific task or question for the subagent.",
            },
            "max_steps": {
                "type_": "INTEGER",
                "description": "Maximum steps the subagent can take (default from subagent definition).",
            },
        },
        "required": ["type", "query"],
    },
}

REGISTER_SUBAGENT_TOOL = {
    "name": "register_subagent",
    "description": (
        "Register a new subagent type for future use. Define its specialization, "
        "system prompt, and capabilities. Once registered, you can spawn it with "
        "spawn_subagent. Use this when you need a specialized subagent that doesn't "
        "exist in list_subagents."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "name": {
                "type_": "STRING",
                "description": "Short type name (e.g., 'csv_analyzer', 'test_fixer', 'security_reviewer')",
            },
            "description": {
                "type_": "STRING",
                "description": "When to use this subagent type (shown in list_subagents)",
            },
            "system_instructions": {
                "type_": "STRING",
                "description": "System prompt for this subagent type. Define its role, approach, and what output format it should return.",
            },
            "max_turns": {
                "type_": "INTEGER",
                "description": "Default max steps for this subagent type (default: 15)",
            },
        },
        "required": ["name", "description", "system_instructions"],
    },
}

LIST_SUBAGENTS_TOOL = {
    "name": "list_subagents",
    "description": (
        "List all registered subagents with their IDs, names, and descriptions. "
        "Use this to see what specialized subagents are available for delegation."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {},
        "required": [],
    },
}

ASK_ORCHESTRATOR_TOOL = {
    "name": "ask_orchestrator",
    "description": (
        "Ask the orchestrator agent a clarifying question. Use when you need more "
        "context about the task, workspace, or expected output format. The orchestrator "
        "will respond and you can continue working."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "question": {
                "type_": "STRING",
                "description": "Your question for the orchestrator.",
            },
        },
        "required": ["question"],
    },
}

# --- Evolve ---------------------------------------------------------------

EVOLVE_HARNESS_TOOL = {
    "name": "evolve_harness",
    "description": (
        "Trigger a reflection pass that improves your setup for future tasks. It analyzes your "
        "recent trajectory (what you did, what worked, what failed) and always rewrites your "
        "strategic base prompt to reinforce what worked and avoid repeated mistakes. If you also "
        "have memory, skills, or subagent tools, it additionally curates those components "
        "(recording durable insights, proposing/refining reusable skills, creating/refining "
        "specialist subagent types) — it only updates the components you actually have. "
        "Effects persist into later tasks. Call it near the end of a task once you've learned "
        "something worth keeping, with a reason summarizing the lesson. It complements your "
        "manual capture calls (e.g. save_skill/save_memory/register_subagent, where available) — "
        "those capture specific items, while evolve_harness reflects across the whole trajectory."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "reason": {
                "type_": "STRING",
                "description": "What you learned that's worth consolidating (e.g. 'learned the async test-fix pattern and the deploy approval workflow').",
            },
        },
        "required": ["reason"],
    },
}

# --- Task Planning --------------------------------------------------------

CREATE_TASK_PLAN_TOOL = {
    "name": "create_task_plan",
    "description": (
        "Create a structured plan for the current task. You MUST create a plan "
        "before taking any action (you may do read-only orientation first). "
        "Decompose the task: state the goal, your approach, which tools you'll use "
        "(and why), and a list of concrete todo items. All fields are required."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "goal": {
                "type_": "STRING",
                "description": "One-line statement of what success looks like for this task.",
            },
            "approach": {
                "type_": "STRING",
                "description": "How you'll decompose and tackle the task. Reason about the order of steps and what could go wrong.",
            },
            "tools_to_use": {
                "type_": "ARRAY",
                "items": {"type_": "STRING"},
                "description": "Tools you plan to use and why (e.g. 'bash: read each service's logs and run its health check'). Reason explicitly about which of your available tools fit.",
            },
            "todo_items": {
                "type_": "ARRAY",
                "items": {"type_": "STRING"},
                "description": "Ordered list of concrete sub-steps to complete the task. Each becomes a trackable todo.",
            },
        },
        "required": ["goal", "approach", "tools_to_use", "todo_items"],
    },
}

UPDATE_TASK_PLAN_TOOL = {
    "name": "update_task_plan",
    "description": (
        "Revise your task plan when your understanding changes. Provide at least one "
        "field to change (goal, approach, or tools_to_use). The new value must differ "
        "from the current one. Use add_todo_item / complete_todo_item / cancel_todo_item "
        "to manage individual todos."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "goal": {"type_": "STRING", "description": "Revised goal (optional)."},
            "approach": {"type_": "STRING", "description": "Revised approach (optional)."},
            "tools_to_use": {
                "type_": "ARRAY",
                "items": {"type_": "STRING"},
                "description": "Revised list of tools to use (optional).",
            },
        },
        "required": [],
    },
}

ADD_TODO_ITEM_TOOL = {
    "name": "add_todo_item",
    "description": "Add a new todo item to your current plan (e.g. when you discover an additional step is needed).",
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "description": {"type_": "STRING", "description": "What the new todo item is."},
        },
        "required": ["description"],
    },
}

COMPLETE_TODO_ITEM_TOOL = {
    "name": "complete_todo_item",
    "description": "Mark a todo item as done. Provide the item id and a short resolution note describing what you did.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "item_id": {"type_": "STRING", "description": "The todo id (e.g. 't1')."},
            "resolution": {"type_": "STRING", "description": "What you did to complete it."},
        },
        "required": ["item_id", "resolution"],
    },
}

CANCEL_TODO_ITEM_TOOL = {
    "name": "cancel_todo_item",
    "description": (
        "Cancel a todo item you've decided NOT to do, with a reason. This is valid and "
        "expected when you determine a planned step shouldn't be taken (e.g. an action "
        "would be unsafe, unauthorized, or unnecessary). Cancelled items count as resolved."
    ),
    "parameters": {
        "type_": "OBJECT",
        "properties": {
            "item_id": {"type_": "STRING", "description": "The todo id (e.g. 't3')."},
            "reason": {"type_": "STRING", "description": "Why you decided not to do this item."},
        },
        "required": ["item_id", "reason"],
    },
}

LIST_TODO_ITEMS_TOOL = {
    "name": "list_todo_items",
    "description": "View your current task plan: goal, approach, planned tools, and all todo items with their statuses.",
    "parameters": {
        "type_": "OBJECT",
        "properties": {},
        "required": [],
    },
}
