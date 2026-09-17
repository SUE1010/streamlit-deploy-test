# Windows용 단독 실행파일(.exe) 만들기

이 폴더는 `streamlit-chatbot.py`(제주시 챗봇)를 Python 설치 없이 실행되는
Windows 실행파일(`JejuChatbot.exe`)로 빌드하기 위한 스크립트입니다.

PyInstaller는 빌드를 실행하는 것과 같은 운영체제용 실행파일만 만들 수 있어서
(크로스 컴파일 불가), **반드시 Windows PC에서 빌드**해야 합니다. 이 저장소는
Linux 환경에서 관리되므로, 아래 절차를 Windows PC에서 직접 실행해 주세요.

## 사전 준비 (Windows PC)

1. [Python 3.10 이상](https://www.python.org/downloads/) 설치
   - 설치 시 "Add python.exe to PATH" 체크
2. 이 저장소를 클론하거나 다운로드

## 빌드 방법

1. 탐색기에서 `windows` 폴더로 이동
2. `build.bat` 더블클릭 (또는 명령 프롬프트에서 `build.bat` 실행)
3. 빌드가 끝나면 `windows\dist\JejuChatbot.exe` 생성됨

## 실행 방법

- `JejuChatbot.exe`를 더블클릭하면 로컬 서버가 뜨고 기본 브라우저가 자동으로 열립니다.
- 사이드바에 본인의 OpenAI API 키를 입력해야 대화가 가능합니다 (키는 저장/전송되지
  않고 그 세션에서만 사용됨).
- 콘솔 창이 함께 뜨는데, 종료하려면 그 창을 닫으면 됩니다.

## 참고 사항

- 첫 실행 시 Windows Defender SmartScreen이 "알 수 없는 게시자" 경고를 띄울 수
  있습니다 — 정식 코드 서명 인증서로 서명하지 않았기 때문입니다. "추가 정보" →
  "실행"으로 진행하면 됩니다.
- 실행파일 용량이 100MB 이상일 수 있습니다 (Streamlit·pandas·pyarrow 등 포함).
- OpenAI API 키를 exe 안에 하드코딩하지 않았습니다 — 매 실행 시 입력해야 합니다.
  키를 고정으로 넣고 싶다면 보안상 권장하지 않지만, `launcher.py`에서
  `os.environ["OPENAI_API_KEY"]`를 설정하고 앱 코드를 그에 맞게 수정하면 됩니다.
