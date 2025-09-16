from nearai.agents.environment import Environment


def run(env: Environment):
    # Your agent code here
    prompt = {"role": "system", "content": "You are part of the NOVA secure file sharing system. Your role is to ensure file collection and verification before passing files to the storage agent."}
    result = env.completion([prompt] + env.list_messages())
    env.add_reply(result)

run(env)

