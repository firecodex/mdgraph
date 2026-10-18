#!/usr/bin/env python3
"""Script to generate a pristine 10-second animated GIF demonstrating a multi-hop query over MCP.

Demonstrates:
- Autonomous AI Agent (Claude/Cursor) connected to MdGraph FastMCP server
- MCP JSON-RPC tool call: `traverse_graph(node_id="checkout_service", max_depth=3)`
- MdGraph executing Recursive Common Table Expression (CTE) vectorless graph traversal
- Multi-hop pathway resolution: checkout_service -> payment_gateway -> vault_auth_policy -> hsm_key_cluster
- Sub-millisecond latency (1.18 ms) and zero-drift deterministic response returned over SSE
- Total runtime: Exactly 10,000 milliseconds (10.0 seconds) looping seamlessly.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

WIDTH = 920
HEIGHT = 540

# Color Palette
BG_COLOR = (11, 15, 25)         # Deep Obsidian #0b0f19
BORDER_COLOR = (30, 38, 56)     # #1e2638
HEADER_BG = (21, 27, 40)        # #151b28
CARD_BG = (17, 22, 34)          # #111622
CODE_BG = (13, 17, 26)          # #0d111a
INNER_BORDER = (42, 52, 74)

# Text & Accents
TEXT_WHITE = (243, 244, 246)    # #f3f4f6
TEXT_MUTED = (156, 163, 175)    # #9ca3af
TEXT_DIM = (107, 114, 128)      # #6b7280

ACCENT_BLUE = (56, 189, 248)    # #38bdf8
ACCENT_CYAN = (56, 189, 248)    # #38bdf8
ACCENT_GREEN = (52, 211, 153)   # #34d399
ACCENT_PURPLE = (167, 139, 250) # #a78bfa
ACCENT_YELLOW = (251, 191, 36)  # #fbbf24
ACCENT_ORANGE = (251, 146, 60)  # #fb923c
ACCENT_RED = (248, 113, 113)    # #f87171

# Window buttons
BTN_RED = (239, 68, 68)
BTN_YELLOW = (245, 158, 11)
BTN_GREEN = (16, 185, 129)


def get_font(size: int):
    font_paths = [
        "/System/Library/Fonts/Menlo.ttc",
        "/System/Library/Fonts/SFNSMono.ttf",
        "/System/Library/Fonts/Monaco.ttf",
        "/Library/Fonts/Arial Unicode.ttf",
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
    return ImageFont.load_default()

FONT_TITLE = get_font(12)
FONT_CODE = get_font(13)
FONT_CODE_BOLD = get_font(13)
FONT_SMALL = get_font(11)
FONT_HEADER = get_font(14)
FONT_BADGE = get_font(10)


def draw_base_window(title: str = "mdgraph-agent -- FastMCP Multi-Hop Traversal"):
    """Draw the outer window container with macOS title bar and status badges."""
    im = Image.new("RGB", (WIDTH, HEIGHT), (6, 9, 15))
    draw = ImageDraw.Draw(im)

    # Outer border / window
    draw.rounded_rectangle([(6, 6), (WIDTH - 6, HEIGHT - 6)], radius=10, fill=BG_COLOR, outline=BORDER_COLOR, width=1)

    # Title bar
    draw.rounded_rectangle([(6, 6), (WIDTH - 6, 42)], radius=10, fill=HEADER_BG)
    draw.rectangle([(6, 30), (WIDTH - 6, 42)], fill=HEADER_BG)
    draw.line([(6, 42), (WIDTH - 6, 42)], fill=BORDER_COLOR, width=1)

    # Window dots
    draw.ellipse([(20, 19), (30, 29)], fill=BTN_RED)
    draw.ellipse([(38, 19), (48, 29)], fill=BTN_YELLOW)
    draw.ellipse([(56, 19), (66, 29)], fill=BTN_GREEN)

    # Title text
    draw.text((WIDTH // 2 - 160, 16), title, font=FONT_TITLE, fill=TEXT_MUTED)

    # Status Pill on the right
    pill_x2 = WIDTH - 20
    pill_x1 = pill_x2 - 168
    draw.rounded_rectangle([(pill_x1, 14), (pill_x2, 34)], radius=8, fill=(16, 42, 28), outline=ACCENT_GREEN, width=1)
    draw.ellipse([(pill_x1 + 9, 21), (pill_x1 + 15, 27)], fill=ACCENT_GREEN)
    draw.text((pill_x1 + 22, 17), "FastMCP SSE: ACTIVE", font=FONT_BADGE, fill=ACCENT_GREEN)

    return im, draw


def draw_badge(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, bg_color: tuple, text_color: tuple, border_color: tuple | None = None, padding_x: int = 8, padding_y: int = 4):
    """Draw a styled badge pill with text."""
    bbox = FONT_BADGE.getbbox(text)
    w = bbox[2] - bbox[0] + padding_x * 2
    h = bbox[3] - bbox[1] + padding_y * 2
    draw.rounded_rectangle([(x, y), (x + w, y + h)], radius=4, fill=bg_color, outline=border_color or bg_color, width=1)
    draw.text((x + padding_x, y + padding_y - 1), text, font=FONT_BADGE, fill=text_color)
    return w


def draw_top_query_card(draw: ImageDraw.ImageDraw, active_step: str = "Query Analysis"):
    """Draw the agent query and status header."""
    draw.rounded_rectangle([(20, 52), (WIDTH - 20, 116)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

    # Badges row
    bx = 34
    bx += draw_badge(draw, bx, 62, "AGENT: CLAUDE 3.5", (30, 25, 55), ACCENT_PURPLE, (60, 50, 110)) + 8
    bx += draw_badge(draw, bx, 62, "PROTOCOL: MCP v4.1", (20, 40, 60), ACCENT_BLUE, (40, 80, 120)) + 8
    draw_badge(draw, bx, 62, f"STAGE: {active_step.upper()}", (45, 38, 15), ACCENT_YELLOW, (90, 75, 30))

    # Query string
    draw.text((34, 88), "Goal: ", font=FONT_CODE_BOLD, fill=ACCENT_BLUE)
    draw.text((80, 88), "Find all security policies required before checkout_service can charge payment", font=FONT_CODE, fill=TEXT_WHITE)


def render_frame(step_index: int, total_steps: int = 20) -> Image.Image:
    """Generate each of the 20 distinct frames covering the complete 10-second lifecycle."""
    im, draw = draw_base_window()

    # Content box coordinates
    c_x1, c_y1, c_x2, c_y2 = 20, 128, WIDTH - 20, HEIGHT - 20

    # =========================================================================
    # PHASE 1 (Frames 0 - 2, 0.0s - 1.2s): Initialization & Strategy Selection
    # =========================================================================
    if step_index == 0:
        draw_top_query_card(draw, "1/5 Tool Selection")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 150), "[agent-core] Connected to MdGraph FastMCP at http://127.0.0.1:8000/sse", font=FONT_CODE, fill=ACCENT_GREEN)
        draw.text((40, 180), "[agent-core] Inspecting registered tools from server:", font=FONT_CODE, fill=TEXT_MUTED)

        tools = [
            ("traverse_graph", "Multi-hop recursive CTE graph traversal (sub-millisecond)", ACCENT_BLUE),
            ("find_path", "Find shortest path between two concepts", TEXT_MUTED),
            ("get_concept", "Fetch metadata, tags, and direct cross-links for a concept", TEXT_MUTED),
            ("search_knowledge", "BM25 full-text keyword search over concept corpus", TEXT_MUTED),
        ]
        ty = 210
        for name, desc, col in tools:
            marker = ">>" if col == ACCENT_BLUE else "  "
            draw.text((50, ty), f"{marker} {name:18} : {desc}", font=FONT_CODE, fill=col)
            ty += 26

        draw.rounded_rectangle([(40, ty + 15), (WIDTH - 40, ty + 55)], radius=6, fill=CODE_BG, outline=INNER_BORDER)
        draw.text((55, ty + 25), "Agent Decision: Bypassing vector search (avoids semantic drift). Using traverse_graph().", font=FONT_CODE, fill=ACCENT_YELLOW)

    elif step_index == 1:
        draw_top_query_card(draw, "1/5 Tool Selection")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 150), "[agent-core] Preparing tool parameters for traverse_graph...", font=FONT_CODE, fill=TEXT_MUTED)
        draw.text((40, 180), "Target Concept : 'checkout_service' (Root Concept)", font=FONT_CODE, fill=TEXT_WHITE)
        draw.text((40, 206), "Max Depth      : 3 hops", font=FONT_CODE, fill=ACCENT_YELLOW)
        draw.text((40, 232), "Direction      : 'out' (outgoing dependencies)", font=FONT_CODE, fill=ACCENT_BLUE)
        draw.text((40, 258), "Tenant ID      : 'default' (auto-resolved)", font=FONT_CODE, fill=TEXT_MUTED)

        draw.rounded_rectangle([(40, 300), (WIDTH - 40, 360)], radius=6, fill=(15, 30, 45), outline=ACCENT_BLUE)
        draw.text((55, 315), "Dispatched tool call: tools/call {name: traverse_graph, depth: 3}", font=FONT_CODE_BOLD, fill=ACCENT_BLUE)
        draw.text((55, 335), "SSE Client streaming payload to FastMCP server daemon...", font=FONT_SMALL, fill=TEXT_MUTED)

    # =========================================================================
    # PHASE 2 (Frames 2 - 5, 1.2s - 2.8s): MCP JSON-RPC Dispatch
    # =========================================================================
    elif step_index in (2, 3, 4, 5):
        draw_top_query_card(draw, "2/5 MCP Protocol Exchange")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 146), "POST /mcp/tools/call HTTP/1.1 (Model Context Protocol JSON-RPC)", font=FONT_CODE_BOLD, fill=ACCENT_BLUE)

        draw.rounded_rectangle([(40, 168), (WIDTH - 40, 362)], radius=6, fill=CODE_BG, outline=INNER_BORDER, width=1)
        rpc_lines = [
            '{',
            '  "jsonrpc": "2.0",',
            '  "id": "req_849204",',
            '  "method": "tools/call",',
            '  "params": {',
            '    "name": "traverse_graph",',
            '    "arguments": {',
            '      "node_id": "checkout_service",',
            '      "max_depth": 3,',
            '      "direction": "out",',
            '      "tenant_id": "default"',
            '    }',
            '  }',
            '}'
        ]
        # Animate lines streaming in
        visible_lines = len(rpc_lines) - 3 if step_index == 4 else (len(rpc_lines) if step_index == 5 else (6 + step_index * 2))
        y = 178
        for line in rpc_lines[:visible_lines]:
            color = ACCENT_ORANGE if "traverse_graph" in line else (ACCENT_YELLOW if "checkout_service" in line else (ACCENT_CYAN if '"method"' in line or '"params"' in line else TEXT_WHITE))
            draw.text((55, y), line, font=FONT_SMALL, fill=color)
            y += 13

        if step_index == 5:
            draw.rounded_rectangle([(40, 374), (WIDTH - 40, 420)], radius=6, fill=(18, 38, 28), outline=ACCENT_GREEN)
            draw.text((55, 384), ">> FastMCP Server: Received tools/call request. Handing off to SQLiteQueryCache.", font=FONT_CODE, fill=ACCENT_GREEN)
            draw.text((55, 402), ">> Zero Python locks | Async Non-blocking Event Loop | Direct SQL pipeline", font=FONT_SMALL, fill=TEXT_MUTED)
        elif step_index == 4:
            draw.rounded_rectangle([(40, 374), (WIDTH - 40, 420)], radius=6, fill=CODE_BG, outline=INNER_BORDER)
            draw.text((55, 384), "Transmitting JSON-RPC frame over HTTP/1.1 SSE transport...", font=FONT_CODE, fill=TEXT_MUTED)

    # =========================================================================
    # PHASE 3 (Frames 6 - 8, 2.8s - 4.2s): Recursive CTE Query Execution
    # =========================================================================
    elif step_index in (6, 7, 8):
        draw_top_query_card(draw, "3/5 Recursive CTE Execution")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 146), "MdGraph Core Engine: Executing SQL Recursive CTE (Relational Cache)", font=FONT_CODE_BOLD, fill=ACCENT_YELLOW)

        draw.rounded_rectangle([(40, 172), (WIDTH - 40, 335)], radius=6, fill=CODE_BG, outline=INNER_BORDER, width=1)
        cte_lines = [
            "WITH RECURSIVE graph_path AS (",
            "    -- Base Case: Seed with root concept 'checkout_service'",
            "    SELECT source_id, target_id, label, 1 as depth, source_id || '->' || target_id as path",
            "    FROM edges WHERE tenant_id = 'default' AND source_id = 'checkout_service'",
            "    UNION ALL",
            "    -- Recursive Step: Join edges table up to max_depth = 3 with loop prevention",
            "    SELECT e.source_id, e.target_id, e.label, gp.depth + 1, gp.path || '->' || e.target_id",
            "    FROM edges e JOIN graph_path gp ON e.source_id = gp.target_id",
            "    WHERE e.tenant_id = 'default' AND gp.depth < 3 AND instr(gp.path, e.target_id) = 0",
            ") SELECT source_id, target_id, label, depth, path FROM graph_path;"
        ]
        y = 180
        for line in cte_lines:
            col = ACCENT_CYAN if line.strip().startswith(("WITH", "SELECT", "FROM", "UNION", "WHERE", "JOIN")) else (TEXT_DIM if line.strip().startswith("--") else TEXT_WHITE)
            draw.text((55, y), line, font=FONT_SMALL, fill=col)
            y += 14

        # Execution gauge
        pct = 0.4 if step_index == 6 else (0.8 if step_index == 7 else 1.0)
        draw.rounded_rectangle([(40, 350), (WIDTH - 40, 362)], radius=6, fill=INNER_BORDER)
        draw.rounded_rectangle([(40, 350), (40 + int((WIDTH - 80) * pct), 362)], radius=6, fill=ACCENT_GREEN)

        status_txt = "Evaluating Hop 1: Direct links..." if step_index == 6 else ("Expanding Hop 2 & Hop 3 recursive CTE joins..." if step_index == 7 else "Execution Complete: 100% path determinism resolved.")
        draw.text((40, 372), f">> {status_txt}", font=FONT_CODE, fill=ACCENT_GREEN if pct == 1.0 else ACCENT_YELLOW)

    # =========================================================================
    # PHASE 4 (Frames 9 - 13, 4.2s - 7.0s): Multi-Hop Graph Traversal Tree
    # =========================================================================
    elif step_index in (9, 10, 11, 12, 13):
        draw_top_query_card(draw, "4/5 Multi-Hop Graph Resolution")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 144), "Topological Traversal Result: 3 Hops Traversed via Recursive CTE", font=FONT_CODE_BOLD, fill=TEXT_WHITE)

        # Draw the 4 nodes in a vertical rail layout with arrow connectors
        nodes = [
            ("HOP 0 (ROOT)", "checkout_service", "System: E-Commerce Storefront", "depends_on", ACCENT_BLUE, (20, 35, 60)),
            ("HOP 1", "payment_gateway", "Service: PCI Payment Router", "authenticates_with", ACCENT_GREEN, (20, 45, 30)),
            ("HOP 2", "vault_auth_policy", "Policy: OKF v0.2 Verified Key Rules", "secures_with", ACCENT_PURPLE, (38, 25, 55)),
            ("HOP 3 (TARGET)", "hsm_key_cluster", "Infrastructure: FIPS 140-3 Hardware", "", ACCENT_YELLOW, (45, 38, 20)),
        ]

        # Determine how many hops are visible based on step
        max_hop_idx = 1 if step_index == 9 else (2 if step_index == 10 else 3)

        curr_y = 172
        for idx in range(max_hop_idx + 1):
            hop_label, node_slug, desc, edge_label, col_accent, col_bg = nodes[idx]

            # Node Box
            card_w = 640
            draw.rounded_rectangle([(40, curr_y), (40 + card_w, curr_y + 40)], radius=6, fill=col_bg, outline=col_accent, width=1)

            # Hop badge inside box
            draw_badge(draw, 50, curr_y + 10, hop_label, (10, 14, 22), col_accent)

            # Node slug
            draw.text((160, curr_y + 11), node_slug, font=FONT_CODE_BOLD, fill=TEXT_WHITE)

            # Node description
            draw.text((360, curr_y + 12), desc, font=FONT_SMALL, fill=TEXT_MUTED)

            # Draw edge connector if not last hop
            if idx < max_hop_idx and edge_label:
                conn_y1 = curr_y + 40
                conn_y2 = conn_y1 + 22

                # Connector line
                draw.line([(80, conn_y1), (80, conn_y2)], fill=ACCENT_ORANGE, width=2)
                draw.line([(80, conn_y2), (105, conn_y2)], fill=ACCENT_ORANGE, width=2)
                draw.polygon([(103, conn_y2 - 3), (110, conn_y2), (103, conn_y2 + 3)], fill=ACCENT_ORANGE)

                # Edge badge
                draw_badge(draw, 118, conn_y1 + 4, f"edge: {edge_label}", (35, 25, 15), ACCENT_ORANGE, (80, 50, 20))

                curr_y = conn_y2 + 6
            else:
                curr_y += 46

        # Benchmark Box at the bottom (progressively revealed)
        if step_index == 12:
            draw.rounded_rectangle([(40, 422), (WIDTH - 40, 468)], radius=6, fill=CODE_BG, outline=INNER_BORDER, width=1)
            draw.text((55, 432), "Calculating traversal execution metrics...", font=FONT_CODE, fill=ACCENT_YELLOW)
            draw.text((55, 448), "Reading CPU time & edge resolution counters...", font=FONT_SMALL, fill=TEXT_MUTED)
        elif step_index >= 13:
            draw.rounded_rectangle([(40, 422), (WIDTH - 40, 468)], radius=6, fill=CODE_BG, outline=ACCENT_GREEN, width=1)
            draw.text((55, 432), "PERFORMANCE: Recursive CTE Query Latency: 1.18 ms", font=FONT_CODE_BOLD, fill=ACCENT_GREEN)
            draw.text((55, 448), "Vector Embeddings: 0 | Hallucination Drift: 0.0% | Git-Backed Source of Truth", font=FONT_SMALL, fill=TEXT_MUTED)

    # =========================================================================
    # PHASE 5 (Frames 14 - 16, 7.0s - 8.5s): FastMCP 200 OK Tool Response
    # =========================================================================
    elif step_index in (14, 15, 16):
        draw_top_query_card(draw, "5/5 MCP Response Delivery")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 146), "HTTP/1.1 200 OK -- FastMCP JSON-RPC Response (SSE Stream)", font=FONT_CODE_BOLD, fill=ACCENT_GREEN)

        draw.rounded_rectangle([(40, 168), (WIDTH - 40, 368)], radius=6, fill=CODE_BG, outline=INNER_BORDER, width=1)
        res_lines = [
            '{',
            '  "jsonrpc": "2.0",',
            '  "result": {',
            '    "root_id": "checkout_service", "depth_reached": 3, "paths_found": 1,',
            '    "path": ["checkout_service", "payment_gateway", "vault_auth_policy", "hsm_key_cluster"],',
            '    "nodes": [',
            '      {"id": "checkout_service", "type": "System", "status": "stable"},',
            '      {"id": "payment_gateway", "type": "Service", "auth": "PCI-DSS"},',
            '      {"id": "vault_auth_policy", "type": "Policy", "okf_version": "0.2"},',
            '      {"id": "hsm_key_cluster", "type": "Infrastructure", "fips": "140-3"}',
            '    ],',
            '    "execution_time_ms": 1.18, "deterministic": true',
            '  }',
            '}'
        ]
        # Progressive stream
        visible_res_lines = 6 if step_index == 14 else len(res_lines)
        y = 176
        for line in res_lines[:visible_res_lines]:
            col = ACCENT_GREEN if '"execution_time_ms"' in line or '"depth_reached"' in line else (ACCENT_YELLOW if '"path"' in line else TEXT_WHITE)
            draw.text((55, y), line, font=FONT_SMALL, fill=col)
            y += 13.5

        if step_index == 14:
            draw.text((55, y + 6), "  ... streaming node metadata array over SSE ...", font=FONT_SMALL, fill=TEXT_MUTED)

        if step_index >= 16:
            draw.rounded_rectangle([(40, 380), (WIDTH - 40, 426)], radius=6, fill=(20, 35, 55), outline=ACCENT_BLUE)
            draw.text((55, 391), ">> MCP Client: Ingested 4 explicit OKF concept nodes + 3 verified edges.", font=FONT_CODE, fill=ACCENT_BLUE)
            draw.text((55, 407), ">> Deterministic context window payload constructed without vector threshold ambiguity.", font=FONT_SMALL, fill=TEXT_MUTED)
        elif step_index == 15:
            draw.rounded_rectangle([(40, 380), (WIDTH - 40, 426)], radius=6, fill=CODE_BG, outline=INNER_BORDER)
            draw.text((55, 399), "Validating OKF v0.2 concept schemas and signature integrity...", font=FONT_CODE, fill=TEXT_MUTED)

    # =========================================================================
    # PHASE 6 (Frames 17 - 19, 8.5s - 10.0s): Grounded Agent Synthesis
    # =========================================================================
    else:
        draw_top_query_card(draw, "Complete: Grounded Answer")
        draw.rounded_rectangle([(c_x1, c_y1), (c_x2, c_y2)], radius=8, fill=CARD_BG, outline=INNER_BORDER, width=1)

        draw.text((40, 144), "Agent Synthesized Answer -- 100% Deterministic & Fact-Grounded:", font=FONT_CODE_BOLD, fill=ACCENT_GREEN)

        # Answer card
        draw.rounded_rectangle([(40, 170), (WIDTH - 40, 370)], radius=6, fill=CODE_BG, outline=INNER_BORDER, width=1)
        answer_text = [
            "Based on exact 3-hop topological traversal over MdGraph FastMCP:",
            "",
            "1. 'checkout_service' cannot directly charge payment credentials.",
            "2. depends_on ──> 'payment_gateway' (PCI-DSS compliant payment router).",
            "3. authenticates_with ──> 'vault_auth_policy' (OKF v0.2 verified cryptographic policy).",
            "4. secures_with ──> 'hsm_key_cluster' (FIPS 140-3 hardware security module).",
            "",
            "Pathway: checkout_service ──► payment_gateway ──► vault_auth_policy ──► hsm_key_cluster",
            "Verified against Git commit 4a9f1b (Zero hallucinations / No vector chunk guessing)."
        ]

        # In step 17: show first 3 lines
        # In step 18: show all 6 steps
        # In step 19: show all lines + badges
        visible_ans_count = 3 if step_index == 17 else (6 if step_index == 18 else len(answer_text))
        y = 182
        for line in answer_text[:visible_ans_count]:
            col = ACCENT_YELLOW if line.startswith("Pathway:") else (ACCENT_GREEN if line.startswith("Verified") else (ACCENT_BLUE if line.startswith("1.") or line.startswith("2.") or line.startswith("3.") or line.startswith("4.") else TEXT_WHITE))
            draw.text((55, y), line, font=FONT_CODE, fill=col)
            y += 19

        if step_index == 17:
            draw.rectangle([(55, y + 10), (67, y + 26)], fill=ACCENT_GREEN)

        # Value Proposition Badges (shown in step 18 and 19)
        if step_index >= 18:
            by = 390
            bx = 40
            bx += draw_badge(draw, bx, by, "OKF v2 COMPATIBLE", (20, 35, 60), ACCENT_BLUE, (40, 70, 120), padding_x=12, padding_y=6) + 12
            bx += draw_badge(draw, bx, by, "SUB-MILLISECOND CTE", (18, 45, 28), ACCENT_GREEN, (35, 90, 55), padding_x=12, padding_y=6) + 12
            bx += draw_badge(draw, bx, by, "ZERO VECTOR CHUNKS", (45, 35, 15), ACCENT_YELLOW, (90, 70, 30), padding_x=12, padding_y=6) + 12
            draw_badge(draw, bx, by, "FASTMCP NATIVE", (38, 25, 55), ACCENT_PURPLE, (75, 50, 110), padding_x=12, padding_y=6)

        loop_txt = "Continuous MCP SSE session active. Seamless loop in 0.5s..." if step_index == 19 else "Synthesizing factual response from verified OKF knowledge..."
        draw.text((40, 436), loop_txt, font=FONT_SMALL, fill=TEXT_MUTED)

    return im


def generate_multihop_gif(output_path: str = "assets/mcp_multihop_demo.gif"):
    """Generate 20-frame animation with exact 10,000 ms total duration."""
    # Frame durations in milliseconds summing to exactly 10,000 ms (10.0 seconds)
    durations = [
        400,  # 0: connect & tool list
        400,  # 1: target concept resolved
        400,  # 2: POST /mcp/tools/call header
        400,  # 3: JSON-RPC body begins
        500,  # 4: JSON-RPC body complete
        500,  # 5: Server received
        400,  # 6: SQL CTE base case
        400,  # 7: SQL CTE recursive join
        400,  # 8: SQL CTE done
        500,  # 9: Hop 0 & Hop 1
        500,  # 10: Hop 2
        500,  # 11: Hop 3
        600,  # 12: Tree complete
        600,  # 13: Benchmark (1.18 ms)
        400,  # 14: FastMCP 200 OK header
        500,  # 15: JSON-RPC response body
        500,  # 16: Result ingested
        600,  # 17: Agent reasoning
        750,  # 18: Agent answer synthesized
        750,  # 19: Value badges & loop transition
    ]

    total_ms = sum(durations)
    print(f"Total animation duration: {total_ms} ms ({total_ms / 1000.0:.2f} seconds)")
    assert total_ms == 10000, f"Duration must be 10000ms! Got {total_ms}"

    frames = [render_frame(i, len(durations)) for i in range(len(durations))]

    # Convert to adaptive 256-color palette
    palette_frames = [f.convert("P", palette=Image.Palette.ADAPTIVE, colors=256) for f in frames]

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    palette_frames[0].save(
        output_path,
        save_all=True,
        append_images=palette_frames[1:],
        duration=durations,
        loop=0,
        optimize=True,
    )
    size_kb = os.path.getsize(output_path) / 1024
    print(f"Generated {output_path}: {len(frames)} frames, {size_kb:.1f} KB, duration: {total_ms / 1000.0}s")


if __name__ == "__main__":
    generate_multihop_gif()
