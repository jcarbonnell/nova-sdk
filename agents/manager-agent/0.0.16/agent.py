from nearai.agents.environment import Environment
import asyncio
import time
from nearai.shared.models import ThreadMode

async def run(env: Environment):
    prompt = {"role": "system", "content": "You are the manager for NOVA secure file sharing. Greet users and guide to commands: 'register group <id>', 'add member <group> <user>', 'revoke member <group> <user>', 'is authorized <group> <user>', 'groups contains <group>'. Route to specialists if matched; otherwise, clarify."}
    messages = env.list_messages()
    if not messages:
        env.add_reply("Hi! I'm the NOVA Manager Agent, assisting with secure file sharing on NEAR. Commands:\n- register group <id>\n- add member <group> <user>\n- revoke member <group> <user>\n- is authorized <group> <user>\n- groups contains <group>\nTry one!")
        env.request_user_input()
        return

    user_query = messages[-1]["content"].strip().lower()
    user_id = "nova-sdk-2.testnet"
    # Greeting handler
    if any(greeting in user_query for greeting in ["hi", "hello", "hey", "help"]):
        env.add_reply("Hi! I'm the NOVA Manager Agent. Here's how to get started:\n- register group <id> (e.g., 'register group test')\n- add member <group> <user> (e.g., 'add member test nova-sdk-2.testnet')\n- revoke member <group> <user>\n- is authorized <group> <user>\n- groups contains <group>\nWhat would you like to do?")
        env.request_user_input()
        return

    # Routing to auth-agent
    auth_ops = ["register group", "add member", "revoke member", "is authorized", "groups contains"]
    expected_op = None
    if any(op in user_query for op in auth_ops):
        # Parse expected_op for poll matching
        if "register group" in user_query:
            expected_op = "register"
        elif "add member" in user_query:
            expected_op = "add"
        elif "revoke member" in user_query:
            expected_op = "revoke"
        elif "is authorized" in user_query:
            expected_op = "authorized"
        elif "groups contains" in user_query:
            expected_op = "groups"

        thread_id = env.run_agent(
            "nova-sdk.near/auth-agent/latest",
            query=user_query,
            thread_mode=ThreadMode.FORK,
        )
        env.add_system_log(f"Forked to auth-agent for {expected_op}: {thread_id}")

        # Improved poll: Count pre-fork messages, wait for new assistant, match op
        pre_fork_count = len(env.list_messages(thread_id=thread_id))
        max_attempts = 15  # Increased for tx finality
        for attempt in range(max_attempts):
            try:
                all_messages = env.list_messages(thread_id=thread_id)
                new_messages = all_messages[pre_fork_count:]  # Only new
                assistant_msgs = [m for m in new_messages if m.get("role") == "assistant"]
                if assistant_msgs:
                    last_assistant = assistant_msgs[-1].get("content", "")
                    # Match op-specific keywords in content
                    if expected_op == "revoke" and ("revoke" in last_assistant.lower() or "rotated" in last_assistant.lower()):
                        env.add_reply(f"✅ Routed to auth-agent: {last_assistant}")
                        env.request_user_input()
                        return
                    elif "success" in last_assistant.lower() or "true" in last_assistant.lower():
                        # General success match, but check for expected
                        if (expected_op == "add" and "add" in last_assistant.lower()) or \
                           (expected_op == "register" and "register" in last_assistant.lower()) or \
                           (expected_op == "authorized" and "authorized" in last_assistant.lower()) or \
                           (expected_op == "groups" and "exists" in last_assistant.lower()):
                            env.add_reply(f"✅ Routed to auth-agent: {last_assistant}")
                            env.request_user_input()
                            return
                time.sleep(1)  # Poll interval
            except Exception as e:
                env.add_system_log(f"Poll error (attempt {attempt}): {e}")
                time.sleep(1)
                continue

        env.add_reply(f"Routed to auth-agent for {expected_op}. Track thread: {thread_id} (timed out after 15s)")
        env.request_user_input()
        return

    # Fallback to LLM
    result = env.completion([prompt] + messages)
    env.add_reply(result)
    env.request_user_input()

# Top-level async run
asyncio.run(run(env))