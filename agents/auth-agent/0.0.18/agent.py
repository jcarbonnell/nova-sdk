from nearai.agents.environment import Environment
import asyncio

async def handle_auth_op(env: Environment, query: str, user_id: str):
    contract_id = env.env_vars.get("CONTRACT_ID", "nova-sdk-2.testnet")
    private_key = env.env_vars.get("NEAR_PRIVATE_KEY")
    near = env.set_near(user_id, private_key, rpc_addr="https://rpc.testnet.near.org")
    try:
        if query.startswith("register group"):
            # Register group
            group_id = query.split("register group ")[1].strip()
            result = await near.call(
                contract_id=contract_id,
                method_name="register_group",
                args={"group_id": group_id},
                amount=100000000000000000000000,  # 0.01 NEAR
            )
            status = 'Success' if 'SuccessValue' in result.status else f'Failed: {result}'
            env.add_reply(f"Register {group_id}: {status}")

        elif query.startswith("add member"):
            # Add member
            parts = query.split("add member ")[1].strip().split()
            if len(parts) < 2:
                env.add_reply("Usage: add member <group_id> <user_id>")
                return
            group_id = parts[0]
            member_id = parts[1]
            result = await near.call(
                contract_id=contract_id,
                method_name="add_group_member",
                args={"group_id": group_id, "user_id": member_id},
                amount=500000000000000000000  # 0.0005 NEAR in yocto
            )
            status = 'Success' if 'SuccessValue' in result.status else f'Failed: {result}'
            env.add_reply(f"Add {member_id} to {group_id}: {status}")

        elif query.startswith("revoke member"):
            # Revoke member
            parts = query.split("revoke member ")[1].strip().split()
            if len(parts) < 2:
                env.add_reply("Usage: revoke member <group_id> <user_id>")
                return
            group_id = parts[0]
            member_id = parts[1]
            result = await near.call(
                contract_id=contract_id,
                method_name="revoke_group_member",
                args={"group_id": group_id, "user_id": member_id},
                amount=500000000000000000000  # 0.0005 NEAR
            )
            status = 'Success' if 'SuccessValue' in result.status else f'Failed: {result}'
            env.add_reply(f"Revoke {member_id} from {group_id} (key rotated): {status}")

        elif query.startswith("is authorized"):
            # Check authorization (view)
            parts = query.split("is authorized ")[1].strip().split()
            if len(parts) < 2:
                env.add_reply("Usage: is authorized <group_id> <user_id>")
                return
            group_id = parts[0]
            member_id = parts[1]
            result = await near.view(
                contract_id=contract_id,
                method_name="is_authorized",
                args={"group_id": group_id, "user_id": member_id}
            )
            env.add_reply(f"Is {member_id} authorized in {group_id}: {result.result}")
        
        elif query.startswith("groups contains"):
            # Check group existence (view)
            group_id = query.split("groups contains ")[1].strip()
            result = await near.view(
                contract_id=contract_id,
                method_name="groups_contains_key",
                args={"group_id": group_id}
            )
            env.add_reply(f"Group {group_id} exists: {result.result}")
            
        else:
            env.add_reply("Invalid command.")
    except Exception as e:
        env.add_reply(f"Error: {str(e)}")

async def run(env: Environment):
    prompt = {"role": "system", "content": "Handling group/members operation within the NOVA secure file sharing system."}
    messages = env.list_messages()
    if messages:
        user_query = messages[-1].get("content", "").strip().lower()
        user_id = "nova-sdk-2.testnet" #env.signer_account_id in production
        await handle_auth_op(env, user_query, user_id)
        env.request_user_input()
        return
    result = env.completion([prompt] + messages)
    env.add_reply(result)
    env.request_user_input()

# Run as async loop
asyncio.run(run(env))