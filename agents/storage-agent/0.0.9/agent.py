from nearai.agents.environment import Environment
import os
import asyncio

def get_file_from_thread_or_local(env: Environment, extensions=(".wav",)) -> tuple:
    """Ingest file: Prefer thread, fallback to local dir scan/copy to thread."""
    # Step 1: Check thread files (drag-and-drop in chat)
    thread_files = env.list_files_from_thread()
    if thread_files:
        file_obj = thread_files[0]  # Take first
        if file_obj.filename.lower().endswith(extensions):
            env.add_system_log(f"Thread file found: {file_obj.filename}")
            return file_obj.filename, True  # Already in thread

    # Step 2: Fallback to local scan (for testing; scan current dir only to start simple)
    try:
        files = os.listdir(".")
        for file in files:
            if file.lower().endswith(extensions):
                file_path = os.path.join(".", file)
                with open(file_path, "rb") as f:
                    file_data = f.read()
                preview = file_data[:10]
                env.add_system_log(f"Local file read: {file}, size: {len(file_data)} bytes, preview: {preview}")
                return file, False  # Now in thread
    except Exception as e:
        env.add_system_log(f"Local scan error: {str(e)}")

    env.add_reply("No .wav file in thread or local dir (./). Drag one or place in agent folder.")
    return None, None

async def run(env: Environment):
    prompt = {"role": "system", "content": "You are part of NOVA secure file sharing. For 'upload file', ingest from thread/local and confirm filename."}
    messages = env.list_messages()
    if not messages:
        env.add_reply("Type 'upload file' to ingest (drag .txt first or place in ./).")
        env.request_user_input()
        return
    user_query = messages[-1]["content"].strip().lower()
    user_id = "nova-sdk-2.testnet"  # Hardcoded for MVP
    if "upload file" in user_query:
        filename, _ = get_file_from_thread_or_local(env)
        if filename:
            env.add_reply(f"✅ Ingested file: {filename} (ready for processing).")
        env.request_user_input()
        return
    # Fallback boilerplate
    result = env.completion([prompt] + messages)
    env.add_reply(result)
    env.request_user_input()

# Run async (match auth-agent)
asyncio.run(run(env))