from nearai.agents.environment import Environment


def run(env: Environment):
    # Your agent code here
    prompt = {"role": "system", "content": "Your role is to assist users of the NOVA secure file sharing system, and developers integrating the NOVA-SDK into their NEAR dApps. You are part of the NOVA secure file sharing system."}
    result = env.completion([prompt] + env.list_messages())
    env.add_reply(result)

run(env)

