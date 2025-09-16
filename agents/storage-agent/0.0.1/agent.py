from nearai.agents.environment import Environment


def run(env: Environment):
    # Your agent code here
    prompt = {"role": "system", "content": "You are dedicated to storing encrypted files to IPFS and record CIDs on the NEAR blockchain. You are part of the NOVA secure filesharing system."}
    result = env.completion([prompt] + env.list_messages())
    env.add_reply(result)

run(env)

