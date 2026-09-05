"""Waiting must not starve status, restart a solve, or swallow cancellation."""
import asyncio
import sys
import time

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from hfss_mcp import server
from hfss_mcp.app import AppContext


@pytest.fixture
def job_context(tmp_path):
    ctx = AppContext(data_dir=tmp_path, use_fake=True)
    job = ctx._new_job_record(kind="parametric", setup="R1")
    ctx._jobs[job["job_id"]] = job
    ctx._persist_jobs()
    yield ctx, job
    ctx.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("state", ["completed", "failed"])
async def test_wait_finishes_early_and_status_remains_available(job_context, state):
    ctx, job = job_context
    server.set_app(ctx)
    try:
        waiting = asyncio.create_task(server.analyze_wait(job["job_id"], 10))
        await asyncio.sleep(0.03)
        assert not waiting.done()
        assert not server.analyze_status(job["job_id"])["done"]
        ctx._finish_job(job, state=state)
        result = await asyncio.wait_for(waiting, 1)
        assert result["done"] and result["wait_reason"] == "terminal"
        assert result["job"]["state"] == state
        assert not result["timed_out"]
        assert len(ctx._jobs) == 1
    finally:
        server.set_app(None)


@pytest.mark.asyncio
async def test_timeout_and_retry_do_not_change_job(job_context):
    ctx, job = job_context
    for _ in range(2):
        result = await ctx.analyze_wait(job["job_id"], 0.02)
        assert result["timed_out"] and not result["done"]
        assert result["job_id"] == job["job_id"]
    assert job["state"] == "running" and len(ctx._jobs) == 1


@pytest.mark.asyncio
async def test_cancel_wait_leaves_solve_running(job_context):
    ctx, job = job_context
    task = asyncio.create_task(ctx.analyze_wait(job["job_id"], 10))
    await asyncio.sleep(0.02)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert job["state"] == "running"
    ctx._finish_job(job, state="completed")
    assert (await ctx.analyze_wait(job["job_id"], 0))["done"]


@pytest.mark.asyncio
async def test_unverified_restored_job_returns_without_blind_wait(job_context, tmp_path):
    writer, job = job_context
    reader = AppContext(data_dir=tmp_path, use_fake=True)
    try:
        start = time.monotonic()
        result = await reader.analyze_wait(job["job_id"], 120)
        assert time.monotonic() - start < 1
        assert result["wait_reason"] == "unverified"
        assert not result["timed_out"] and not result["done"]
        writer._finish_job(job, state="completed")
        assert (await reader.analyze_wait(job["job_id"], 0))["done"]
    finally:
        reader.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("timeout", [-1, 121, float("nan"), float("inf")])
async def test_invalid_timeout(job_context, timeout):
    ctx, job = job_context
    with pytest.raises(ValueError):
        await ctx.analyze_wait(job["job_id"], timeout)


@pytest.mark.asyncio
async def test_missing_job_and_public_schema(job_context):
    ctx, _ = job_context
    server.set_app(ctx)
    try:
        result = await server.analyze_wait("missing", 0)
        assert not result["ok"]
        tools = await server.mcp.list_tools()
        tool = next(t for t in tools if t.name == "analyze_wait")
        assert tool.inputSchema["properties"]["timeout_s"]["default"] == 45
    finally:
        server.set_app(None)


@pytest.mark.asyncio
async def test_stdio_wait_status_cancellation_and_completion(tmp_path):
    # A real MCP subprocess and protocol session, with a synthetic solve worker.
    code = '''
import sys, threading
from hfss_mcp.app import AppContext
from hfss_mcp import server
ctx = AppContext(data_dir=sys.argv[1], use_fake=True)
job = ctx._new_job_record(kind="parametric", setup="R1")
job["job_id"] = "probe"
ctx._owned_job_ids.add("probe")
ctx._jobs["probe"] = job
ctx._persist_jobs()
server.set_app(ctx)
threading.Timer(3, lambda: ctx._finish_job(job, state="completed")).start()
server.mcp.run(transport="stdio")
'''
    params = StdioServerParameters(
        command=sys.executable, args=["-c", code, str(tmp_path / "server")]
    )
    async with (
        stdio_client(params) as (read, write),
        ClientSession(read, write) as client,
    ):
        await client.initialize()
        first = await client.call_tool("analyze_wait", {"job_id": "probe", "timeout_s": 0})
        assert first.structuredContent["timed_out"]
        waiting = asyncio.create_task(
            client.call_tool("analyze_wait", {"job_id": "probe", "timeout_s": 10})
        )
        await asyncio.sleep(0.05)
        status = await asyncio.wait_for(
            client.call_tool("analyze_status", {"job_id": "probe"}), 1
        )
        assert not status.structuredContent["done"]
        assert not waiting.done()
        waiting.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiting
        final = await asyncio.wait_for(
            client.call_tool("analyze_wait", {"job_id": "probe", "timeout_s": 10}), 5
        )
        assert final.structuredContent["wait_reason"] == "terminal"
        assert final.structuredContent["job"]["state"] == "completed"
