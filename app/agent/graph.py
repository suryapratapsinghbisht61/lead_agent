"""Wire the nodes into a LangGraph graph.

Main graph:
    START -> plan_queries -> search_sources -> extract_candidates -> dedupe -> pick_batch
    pick_batch --(Send x N, in parallel)--> process_lead --> pick_batch      (loop)
    pick_batch --> plan_queries   (need more leads: new search round)
    pick_batch --> save_results -> END

process_lead is itself a small graph (a "subgraph"), run once per lead:
    research_lead -> qualify -> write_outreach -> finish_lead
                            \\-> finish_lead  (low fit / skipped: no message needed)
"""

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.dedupe import dedupe
from app.agent.nodes.extract_candidates import extract_candidates
from app.agent.nodes.pick_batch import pick_batch, route_after_pick
from app.agent.nodes.plan_queries import plan_queries
from app.agent.nodes.qualify import qualify, route_after_qualify
from app.agent.nodes.research_lead import research_lead
from app.agent.nodes.save_results import save_results
from app.agent.nodes.search_sources import search_sources
from app.agent.nodes.write_outreach import finish_lead, write_outreach
from app.agent.state import AgentState, LeadInput, LeadOutput, LeadState, RunContext


def build_lead_graph():
    g = StateGraph(LeadState, context_schema=RunContext, input_schema=LeadInput, output_schema=LeadOutput)
    g.add_node("research_lead", research_lead)
    g.add_node("qualify", qualify)
    g.add_node("write_outreach", write_outreach)
    g.add_node("finish_lead", finish_lead)

    g.add_edge(START, "research_lead")
    g.add_edge("research_lead", "qualify")
    g.add_conditional_edges("qualify", route_after_qualify, ["write_outreach", "finish_lead"])
    g.add_edge("write_outreach", "finish_lead")
    g.add_edge("finish_lead", END)
    return g.compile()


def build_graph():
    g = StateGraph(AgentState, context_schema=RunContext)
    g.add_node("plan_queries", plan_queries)
    g.add_node("search_sources", search_sources)
    g.add_node("extract_candidates", extract_candidates)
    g.add_node("dedupe", dedupe)
    g.add_node("pick_batch", pick_batch)
    g.add_node("process_lead", build_lead_graph())  # a compiled graph can be used as a node
    g.add_node("save_results", save_results)

    g.add_edge(START, "plan_queries")
    g.add_edge("plan_queries", "search_sources")
    g.add_edge("search_sources", "extract_candidates")
    g.add_edge("extract_candidates", "dedupe")
    g.add_edge("dedupe", "pick_batch")
    g.add_conditional_edges("pick_batch", route_after_pick, ["process_lead", "plan_queries", "save_results"])
    g.add_edge("process_lead", "pick_batch")  # waits for ALL parallel leads, then decides again
    g.add_edge("save_results", END)
    return g.compile()


graph = build_graph()


def mermaid() -> str:
    """Diagram source. Paste into https://mermaid.live or view docs/graph.md on GitHub."""
    return graph.get_graph(xray=1).draw_mermaid()
