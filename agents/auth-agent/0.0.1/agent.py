from nearai.agents.environment import Environment


def run(env: Environment):
    # Your agent code here
    prompt = {"role": "system", "content": "You are dedicated to handling group registration within the NOVA secure file sharing system."}
    result = env.completion([prompt] + env.list_messages())
    env.add_reply(result)

run(env)

