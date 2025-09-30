from fastmcp import FastMCP

mcp = FastMCP(name="NovaMCP")

if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1", port=8000)