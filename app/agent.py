# ruff: noqa
import datetime
import json
import re
from typing import Any, AsyncGenerator

from google.adk.workflow import Workflow, START
from google.adk.agents import LlmAgent
from google.adk.tools import AgentTool
from google.adk.models import Gemini
from google.adk.events.event import Event
from google.adk.events.event_actions import EventActions
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.adk.apps import App, ResumabilityConfig
from pydantic import BaseModel, Field
from google.genai import types

from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from .config import config

# -----------------------------------------------------------------------------
# 1. Local MCP Server Toolset definition
# -----------------------------------------------------------------------------
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command="uv",
            args=["run", "python", "-m", "app.mcp_server"]
        )
    )
)

# -----------------------------------------------------------------------------
# 2. Output Schemas for Specialized Agents
# -----------------------------------------------------------------------------
class RoutePlan(BaseModel):
    hazard_analysis: str = Field(description="Analysis of local hazards present in the area.")
    evacuation_routes: list[str] = Field(description="Step-by-step description of recommended evacuation routes.")
    safe_zones: list[str] = Field(description="Identified safe assembly points or shelters.")

class Checklist(BaseModel):
    essential_items: list[str] = Field(description="Standard emergency items like water, food, flashlight, batteries.")
    specialized_items: list[str] = Field(description="Items customized based on specific hazards (e.g. masks for wildfire, life jackets for flood) and family details.")
    action_steps: list[str] = Field(description="Pre-evacuation checklists and tasks (e.g., shut off utilities, grab documents).")

# -----------------------------------------------------------------------------
# 3. Specialized Sub-Agents (with MCP tools wired)
# -----------------------------------------------------------------------------
route_planner_agent = LlmAgent(
    name="RoutePlannerAgent",
    model=Gemini(model=config.model),
    instruction="""You are a professional disaster response and evacuation planning specialist.
Your job is to analyze geographical hazards and plan the safest evacuation routes and assembly zones.
You have access to tools from the MCP server to check weather conditions, active hazard warnings, and emergency shelters.
Always structure your response according to the provided schema. Do not make up information.
Use local safety guidelines if available.""",
    output_schema=RoutePlan,
    description="Specialized agent that generates custom evacuation routes, maps hazard zones, and identifies assembly locations.",
    tools=[mcp_toolset]
)

checklist_specialist_agent = LlmAgent(
    name="ChecklistSpecialistAgent",
    model=Gemini(model=config.model),
    instruction="""You are a family safety planner.
Your job is to generate custom emergency checklists. Consider the specific hazards, family composition, medical conditions, pets, and dietary needs.
You have access to tools from the MCP server to check weather conditions, active hazard warnings, and emergency shelters.
Always structure your response according to the provided schema. Be practical and detailed.""",
    output_schema=Checklist,
    description="Specialized agent that generates customized emergency kits, safety lists, and action items.",
    tools=[mcp_toolset]
)

# Wrap sub-agents in AgentTools so they are callable by the Coordinator/Orchestrator
route_planner_tool = AgentTool(agent=route_planner_agent)
checklist_tool = AgentTool(agent=checklist_specialist_agent)

# -----------------------------------------------------------------------------
# 4. Coordinator Agent
# -----------------------------------------------------------------------------
coordinator_agent = LlmAgent(
    name="CoordinatorAgent",
    model=Gemini(model=config.model),
    instruction="""You are the central Disaster Preparedness Coordinator.
Your job is to assist the user by coordinating the creation of a comprehensive emergency plan.
You have access to two agent tools:
1. `RoutePlannerAgent` - Call this to get custom route planning and hazard assessment.
2. `ChecklistSpecialistAgent` - Call this to get a customized safety checklist.

When a user asks for assistance, you must ALWAYS call BOTH tools (where applicable) to gather detailed routes and checklists.
Once you receive results from the tools, synthesize them into a clear, unified, and encouraging disaster preparedness plan.
Briefly summarize the plan for the user, highlighting the key safety actions, evacuation steps, and checklist items.
Write your final synthesized response clearly.""",
    tools=[route_planner_tool, checklist_tool],
    output_key="draft_plan"
)

# -----------------------------------------------------------------------------
# 5. Helper function to extract user text
# -----------------------------------------------------------------------------
def get_user_text(content: Any) -> str:
    if isinstance(content, types.Content):
        parts = content.parts or []
        return " ".join(part.text for part in parts if part.text)
    elif isinstance(content, str):
        return content
    return str(content)

# -----------------------------------------------------------------------------
# 6. Workflow Node Functions
# -----------------------------------------------------------------------------
def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    text = get_user_text(node_input)

    audit_log = {
        "timestamp": datetime.datetime.now().isoformat(),
        "session_id": ctx.session.id,
        "input_length": len(text),
        "pii_detected": False,
        "injection_detected": False,
        "violation_detected": False,
        "decision": "pass"
    }

    # A. PII Scrubbing
    cleaned_text = text
    # Scrub GPS coordinates
    coord_pattern = r"[-+]?\d{1,2}\.\d+,\s*[-+]?\d{1,3}\.\d+"
    if re.search(coord_pattern, cleaned_text):
        cleaned_text = re.sub(coord_pattern, "[GPS_COORDINATES_REDACTED]", cleaned_text)
        audit_log["pii_detected"] = True

    # Scrub Emails
    email_pattern = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"
    if re.search(email_pattern, cleaned_text):
        cleaned_text = re.sub(email_pattern, "[EMAIL_REDACTED]", cleaned_text)
        audit_log["pii_detected"] = True

    # Scrub SSN
    ssn_pattern = r"\b\d{3}-\d{2}-\d{4}\b"
    if re.search(ssn_pattern, cleaned_text):
        cleaned_text = re.sub(ssn_pattern, "[SSN_REDACTED]", cleaned_text)
        audit_log["pii_detected"] = True

    # B. Prompt Injection detection
    injection_keywords = [
        "ignore previous instructions", "system prompt", "override rules",
        "bypass security", "ignore your instructions", "reveal your"
    ]
    for keyword in injection_keywords:
        if keyword in cleaned_text.lower():
            audit_log["injection_detected"] = True
            audit_log["decision"] = "security_violation"
            print(json.dumps({"severity": "CRITICAL", "message": f"Prompt injection attempt detected: {keyword}", "log": audit_log}))
            return Event(
                output="Security Event: Prompt injection attempt detected.",
                actions=EventActions(route="security_violation")
            )

    # C. Domain-specific rule (harmful requests)
    harmful_keywords = ["make a bomb", "sabotage water supply", "chemical attack"]
    for kw in harmful_keywords:
        if kw in cleaned_text.lower():
            audit_log["violation_detected"] = True
            audit_log["decision"] = "security_violation"
            print(json.dumps({"severity": "CRITICAL", "message": f"Harmful request detected: {kw}", "log": audit_log}))
            return Event(
                output="Security Event: Harmful activity requested.",
                actions=EventActions(route="security_violation")
            )

    ctx.state["safe_user_input"] = cleaned_text
    print(json.dumps({"severity": "INFO", "message": "Input passed security checks", "log": audit_log}))
    return Event(
        output=cleaned_text,
        actions=EventActions(route="pass")
    )


async def security_violation_handler(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    text = get_user_text(node_input)
    reply = f"🛑 **Security Violation Detected**\n\nYour request was blocked: {text}\n\nPlease rephrase your request without sensitive or harmful content."
    yield Event(content=types.Content(role="model", parts=[types.Part.from_text(text=reply)]))


async def human_approval(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    # If we haven't received the approval input yet, ask for it
    if not ctx.resume_inputs or "approve" not in ctx.resume_inputs:
        ctx.state["pending_plan"] = get_user_text(node_input)
        yield RequestInput(
            interrupt_id="approve",
            message="Please review the generated disaster preparedness plan above. Do you approve and want to finalize this plan? (Reply 'yes' or 'no')"
        )
        return

    # Check user response from resume_inputs
    user_response = ctx.resume_inputs["approve"].lower().strip()
    if "yes" in user_response or user_response == "y":
        ctx.state["approved"] = True
        yield Event(output=ctx.state.get("pending_plan", node_input))
    else:
        ctx.state["approved"] = False
        yield Event(output="The evacuation plan was not approved. Let me know if you want to make adjustments or try again.")


async def final_output(ctx: Context, node_input: Any) -> AsyncGenerator[Event, None]:
    approved = ctx.state.get("approved", False)
    plan_text = get_user_text(node_input)
    if approved:
        text = f"✅ **Disaster Preparedness Plan — Finalized**\n\n{plan_text}"
    else:
        text = f"❌ **Plan Not Approved**\n\n{plan_text}"

    yield Event(content=types.Content(role="model", parts=[types.Part.from_text(text=text)]))


# -----------------------------------------------------------------------------
# 7. Workflow Orchestration Graph
# -----------------------------------------------------------------------------
# Routing edges use dict syntax: (source, {"route": target})
root_agent = Workflow(
    name="disaster_prep_workflow",
    edges=[
        (START, security_checkpoint),
        (security_checkpoint, {
            "pass": coordinator_agent,
            "security_violation": security_violation_handler,
        }),
        (coordinator_agent, human_approval),
        (human_approval, final_output),
    ]
)

# -----------------------------------------------------------------------------
# 8. App Container definition
# -----------------------------------------------------------------------------
app = App(
    root_agent=root_agent,
    name="app",
    resumability_config=ResumabilityConfig(is_resumable=True)
)
