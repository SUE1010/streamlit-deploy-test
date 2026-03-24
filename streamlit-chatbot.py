from openai import OpenAI
import streamlit as st

with st.sidebar:
    openai_api_key = st.text_input("OpenAI API Key", key="chatbot_api_key", type="password")
    print(openai_api_key)
    "[Get an OpenAI API key](https://platform.openai.com/account/api-keys)"
    "[View the source code](https://github.com/streamlit/llm-examples/blob/main/Chatbot.py)"
    "[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/streamlit/llm-examples?quickstart=1)"

st.title("💬 제주시 챗봇")
st.caption("🚀 A Streamlit chatbot powered by OpenAI")

#위젯의 값이 바뀌면 위에서부터 새롭게 실행 -> 변수값이 reset 될수 있음
#새롭게 실행되더라도 변수를 고정시켜야 할때 st.session_state에 보관해야됨
#st.session_state["messages"]  : 대화내용을 기록할 messages를 초기화

if "messages" not in st.session_state:
    st.session_state["messages"] = [{"role": "assistant", "content": "How can I help you?"}]

#대화내용을 출력
for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

#사용자 입력(출력)을 대기
if prompt := st.chat_input():
    if not openai_api_key:
        st.info("Please add your OpenAI API key to continue.")
        st.stop()

    client = OpenAI(api_key=openai_api_key)
    # client = OpenAI()    
    #사용자 입력(질문) = 대화내용 기록
    st.session_state.messages.append({"role": "user", "content": prompt})                                       
    #user아이콘과 대화내용 출력
    st.chat_message("user").write(prompt)                                                                        
    #LLM 질의 및 응답 수신
    response = client.chat.completions.create(
        model="gpt-3.5-turbo", 
        messages=st.session_state.messages)              
    msg = response.choices[0].message.content
    # LLM의 응답 기록
    st.session_state.messages.append({"role": "assistant", "content": msg})
    #user아이콘과 대화내용(LLM의 답변) 출력
    st.chat_message("assistant").write(msg)

