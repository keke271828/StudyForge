"""Start the MCP server as external clients do and list its tools."""

import asyncio
import os
import sys
from tempfile import TemporaryDirectory

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def main() -> None:
    original_directory = os.getcwd()
    with TemporaryDirectory() as directory:
        try:
            os.chdir(directory)
            frozen = os.environ.get("STUDYFORGE_MCP_EXE")
            server = StdioServerParameters(command=frozen or sys.executable,
                                           args=["--mcp"] if frozen else ["-m", "studyforge.mcp_server"])
            async with stdio_client(server) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    names = {tool.name for tool in (await session.list_tools()).tools}
                    required = {"list_projects", "list_categories", "read_source", "read_assignment",
                                "submit_code_file", "attach_artifact"}
                    print(sorted(names))
                    if not required.issubset(names):
                        raise RuntimeError(f"MCP 缺少工具：{required - names}")
        finally:
            os.chdir(original_directory)


if __name__ == "__main__":
    asyncio.run(main())
