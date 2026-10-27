import asyncio
import os
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from studyforge.db import create_project


def test_mcp_round_trip():
    project = create_project("MCP smoke")

    async def check():
        params = StdioServerParameters(command=sys.executable, args=["-m", "studyforge.mcp_server"], env=dict(os.environ))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {"list_projects", "read_source", "submit_python_file", "attach_artifact"} <= names
                result = await session.call_tool("list_projects", {})
                assert any(project["id"] == item["id"] for item in result.structuredContent["result"])

    asyncio.run(check())
