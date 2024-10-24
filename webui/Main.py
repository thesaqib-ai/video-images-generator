import os
import re
import sys

# Add the root directory of the project to the system path to allow importing modules from the project
root_dir = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
if root_dir not in sys.path:
    sys.path.append(root_dir)
    print("******** sys.path ********")
    print(sys.path)
    print("")

import platform
from uuid import uuid4

import streamlit as st
from openai import OpenAI
from io import BytesIO
from PIL import Image
from loguru import logger
import requests

st.set_page_config(
    page_title="MoneyPrinterTurbo",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="auto"
)

# from app.config import config
from app.models.const import FILE_TYPE_IMAGES, FILE_TYPE_VIDEOS
from app.models.schema import VideoAspect, VideoConcatMode, VideoParams
from app.services import llm, voice
from app.services import task as tm
from app.utils import utils

hide_streamlit_style = """
<style>#root > div:nth-child(1) > div > div > div > div > section > div {padding-top: 0rem;}</style>
"""
st.markdown(hide_streamlit_style, unsafe_allow_html=True)
st.title(f"MoneyPrinterTurbo")

support_locales = [
    "zh-CN",
    "zh-HK",
    "zh-TW",
    "de-DE",
    "en-US",
    "fr-FR",
    "vi-VN",
    "th-TH",
]

font_dir = os.path.join(root_dir, "resource", "fonts")
song_dir = os.path.join(root_dir, "resource", "songs")
i18n_dir = os.path.join(root_dir, "webui", "i18n")

if "video_subject" not in st.session_state:
    st.session_state["video_subject"] = ""
if "video_script" not in st.session_state:
    st.session_state["video_script"] = ""
if "video_terms" not in st.session_state:
    st.session_state["video_terms"] = ""
if "ui_language" not in st.session_state:
    st.session_state["ui_language"] = ui_language


def get_all_fonts():
    fonts = []
    for root, dirs, files in os.walk(font_dir):
        for file in files:
            if file.endswith(".ttf") or file.endswith(".ttc"):
                fonts.append(file)
    fonts.sort()
    return fonts


def get_all_songs():
    songs = []
    for root, dirs, files in os.walk(song_dir):
        for file in files:
            if file.endswith(".mp3"):
                songs.append(file)
    return songs


def open_task_folder(task_id):
    try:
        sys = platform.system()
        path = os.path.join(root_dir, "storage", "tasks", task_id)
        if os.path.exists(path):
            if sys == "Windows":
                os.system(f"start {path}")
            if sys == "Darwin":
                os.system(f"open {path}")
    except Exception as e:
        logger.error(e)


def scroll_to_bottom():
    js = """
    <script>
        console.log("scroll_to_bottom");
        function scroll(dummy_var_to_force_repeat_execution){
            var sections = parent.document.querySelectorAll('section.main');
            console.log(sections);
            for(let index = 0; index<sections.length; index++) {
                sections[index].scrollTop = sections[index].scrollHeight;
            }
        }
        scroll(1);
    </script>
    """
    st.components.v1.html(js, height=0, width=0)


def init_log():
    logger.remove()
    _lvl = "DEBUG"

    def format_record(record):
        # 获取日志记录中的文件全路径
        file_path = record["file"].path
        # 将绝对路径转换为相对于项目根目录的路径
        relative_path = os.path.relpath(file_path, root_dir)
        # 更新记录中的文件路径
        record["file"].path = f"./{relative_path}"
        # 返回修改后的格式字符串
        record["message"] = record["message"].replace(root_dir, ".")

        _format = (
            "<green>{time:%Y-%m-%d %H:%M:%S}</> | "
            + "<level>{level}</> | "
            + '"{file.path}:{line}":<blue> {function}</> '
            + "- <level>{message}</>"
            + "\n"
        )
        return _format

    logger.add(
        sys.stdout,
        level=_lvl,
        format=format_record,
        colorize=True,
    )


init_log()
locales = utils.load_locales(i18n_dir)


def tr(key):
    loc = locales.get(st.session_state["ui_language"], {})
    return loc.get("Translation", {}).get(key, key)


st.write(tr("Get Help"))

if not st.secrets["app"].get("hide_config", False):
    with st.expander(tr("Basic Settings"), expanded=True):
        config_panels = st.columns(3)
        left_config_panel = config_panels[0]
        middle_config_panel = config_panels[1]
        right_config_panel = config_panels[2]
        with left_config_panel:
            display_languages = []
            selected_index = 0
            for i, code in enumerate(locales.keys()):
                display_languages.append(f"{code} - {locales[code].get('Language')}")
                if code == st.session_state["ui_language"]:
                    selected_index = i

            selected_language = st.selectbox(
                tr("Language"), options=display_languages, index=selected_index
            )
            if selected_language:
                code = selected_language.split(" - ")[0].strip()
                st.session_state["ui_language"] = code

            # 是否禁用日志显示
            hide_log = st.checkbox(
                tr("Hide Log"), value=st.secrets["app"].get("hide_log", False)
            )

        with middle_config_panel:
            llm_providers = [
                "OpenAI",
                "Moonshot",
                "Azure",
                "Qwen",
                "DeepSeek",
                "Gemini",
                "Ollama",
                "G4f",
                "OneAPI",
                "Cloudflare",
                "ERNIE",
            ]
            saved_llm_provider_index = llm_providers.index(llm_provider)

            llm_provider = st.selectbox(
                tr("LLM Provider"),
                options=llm_providers,
                index=saved_llm_provider_index,
            )
            llm_provider = llm_provider.lower()
            st.secrets["app"]["llm_provider"] = llm_provider

            llm_api_key = st.secrets["app"].get(f"{llm_provider}_api_key", "")
            llm_secret_key = st.secrets["app"].get(f"{llm_provider}_secret_key", "")  # only for baidu ernie
            llm_base_url = st.secrets["app"].get(f"{llm_provider}_base_url", "")
            llm_model_name = st.secrets["app"].get(f"{llm_provider}_model_name", "")
            llm_account_id = st.secrets["app"].get(f"{llm_provider}_account_id", "")

            tips = ""
            if llm_provider == "ollama":
                if not llm_model_name:
                    llm_model_name = "qwen:7b"
                if not llm_base_url:
                    llm_base_url = "http://localhost:11434/v1"

                with llm_helper:
                    tips = """
                           ##### Ollama配置说明
                           - **API Key**: 随便填写，比如 123
                           - **Base Url**: 一般为 http://localhost:11434/v1
                              - 如果 `MoneyPrinterTurbo` 和 `Ollama` **不在同一台机器上**，需要填写 `Ollama` 机器的IP地址
                              - 如果 `MoneyPrinterTurbo` 是 `Docker` 部署，建议填写 `http://host.docker.internal:11434/v1`
                           - **Model Name**: 使用 `ollama list` 查看，比如 `qwen:7b`
                           """

            if llm_provider == "openai":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                           ##### OpenAI 配置说明
                           > 需要VPN开启全局流量模式
                           - **API Key**: [点击到官网申请](https://platform.openai.com/api-keys)
                           - **Base Url**: 可以留空
                           - **Model Name**: 填写**有权限**的模型，[点击查看模型列表](https://platform.openai.com/settings/organization/limits)
                           """

            if llm_provider == "moonshot":
                if not llm_model_name:
                    llm_model_name = "moonshot-v1-8k"
                with llm_helper:
                    tips = """
                           ##### Moonshot 配置说明
                           - **API Key**: [点击到官网申请](https://platform.moonshot.cn/console/api-keys)
                           - **Base Url**: 固定为 https://api.moonshot.cn/v1
                           - **Model Name**: 比如 moonshot-v1-8k，[点击查看模型列表](https://platform.moonshot.cn/docs/intro#%E6%A8%A1%E5%9E%8B%E5%88%97%E8%A1%A8)
                           """
            if llm_provider == "oneapi":
                if not llm_model_name:
                    llm_model_name = (
                        "claude-3-5-sonnet-20240620"  # 默认模型，可以根据需要调整
                    )
                with llm_helper:
                    tips = """
                        ##### OneAPI 配置说明
                        - **API Key**: 填写您的 OneAPI 密钥
                        - **Base Url**: 填写 OneAPI 的基础 URL
                        - **Model Name**: 填写您要使用的模型名称，例如 claude-3-5-sonnet-20240620
                        """

            if llm_provider == "qwen":
                if not llm_model_name:
                    llm_model_name = "qwen-max"
                with llm_helper:
                    tips = """
                           ##### 通义千问Qwen 配置说明
                           - **API Key**: [点击到官网申请](https://dashscope.console.aliyun.com/apiKey)
                           - **Base Url**: 留空
                           - **Model Name**: 比如 qwen-max，[点击查看模型列表](https://help.aliyun.com/zh/dashscope/developer-reference/model-introduction#3ef6d0bcf91wy)
                           """

            if llm_provider == "g4f":
                if not llm_model_name:
                    llm_model_name = "gpt-3.5-turbo"
                with llm_helper:
                    tips = """
                           ##### gpt4free 配置说明
                           > [GitHub开源项目](https://github.com/xtekky/gpt4free)，可以免费使用GPT模型，但是**稳定性较差**
                           - **API Key**: 随便填写，比如 123
                           - **Base Url**: 留空
                           - **Model Name**: 比如 gpt-3.5-turbo，[点击查看模型列表](https://github.com/xtekky/gpt4free/blob/main/g4f/models.py#L308)
                           """
            if llm_provider == "azure":
                with llm_helper:
                    tips = """
                           ##### Azure 配置说明
                           > [点击查看如何部署模型](https://learn.microsoft.com/zh-cn/azure/ai-services/openai/how-to/create-resource)
                           - **API Key**: [点击到Azure后台创建](https://portal.azure.com/#view/Microsoft_Azure_ProjectOxford/CognitiveServicesHub/~/OpenAI)
                           - **Base Url**: 留空
                           - **Model Name**: 填写你实际的部署名
                           """

            if llm_provider == "gemini":
                if not llm_model_name:
                    llm_model_name = "gemini-1.0-pro"

                with llm_helper:
                    tips = """
                            ##### Gemini 配置说明
                            > 需要VPN开启全局流量模式
                           - **API Key**: [点击到官网申请](https://ai.google.dev/)
                           - **Base Url**: 留空
                           - **Model Name**: 比如 gemini-1.0-pro
                           """

            if llm_provider == "deepseek":
                if not llm_model_name:
                    llm_model_name = "deepseek-chat"
                if not llm_base_url:
                    llm_base_url = "https://api.deepseek.com"
                with llm_helper:
                    tips = """
                           ##### DeepSeek 配置说明
                           - **API Key**: [点击到官网申请](https://platform.deepseek.com/api_keys)
                           - **Base Url**: 固定为 https://api.deepseek.com
                           - **Model Name**: 固定为 deepseek-chat
                           """

            if llm_provider == "ernie":
                with llm_helper:
                    tips = """
                           ##### 百度文心一言 配置说明
                           - **API Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                           - **Secret Key**: [点击到官网申请](https://console.bce.baidu.com/qianfan/ais/console/applicationConsole/application)
                           - **Base Url**: 填写 **请求地址** [点击查看文档](https://cloud.baidu.com/doc/WENXINWORKSHOP/s/jlil56u11#%E8%AF%B7%E6%B1%82%E8%AF%B4%E6%98%8E)
                           """

            if tips and st.secrets["ui"]["language"] == "zh":
                st.warning(
                    "中国用户建议使用 **DeepSeek** 或 **Moonshot** 作为大模型提供商\n- 国内可直接访问，不需要VPN \n- 注册就送额度，基本够用"
                )
                st.info(tips)

            st_llm_api_key = st.text_input(
                tr("API Key"), value=st.secrets.get("llm_api_key", ""), type="password"
            )
            st_llm_base_url = st.text_input(tr("Base Url"), value=st.secrets.get("llm_base_url", ""))
            st_llm_model_name = ""
            llm_provider = st.secrets["llm_provider"]

            if llm_provider != "ernie":
                st_llm_model_name = st.text_input(
                    tr("Model Name"),
                    value=st.secrets.get(f"{llm_provider}_model_name", ""),
                    key=f"{llm_provider}_model_name_input",
                )
            else:
                st_llm_model_name = None
            
            if st_llm_api_key:
                st.secrets["app"][f"{llm_provider}_api_key"] = st_llm_api_key
            if st_llm_base_url:
                st.secrets["app"][f"{llm_provider}_base_url"] = st_llm_base_url
            if st_llm_model_name:
                st.secrets["app"][f"{llm_provider}_model_name"] = st_llm_model_name
            if llm_provider == "ernie":
                st_llm_secret_key = st.text_input(
                    tr("Secret Key"), value=st.secrets.get("llm_secret_key", ""), type="password"
                )
                st.secrets["app"][f"{llm_provider}_secret_key"] = st_llm_secret_key
            
            if llm_provider == "cloudflare":
                st_llm_account_id = st.text_input(
                    tr("Account ID"), value=st.secrets.get("llm_account_id", "")
                )
                if st_llm_account_id:
                    st.secrets["app"][f"{llm_provider}_account_id"] = st_llm_account_id

        with right_config_panel:
        
            def get_keys_from_secrets(cfg_key):
                api_keys = st.secrets["app"].get(cfg_key, [])
                if isinstance(api_keys, str):
                    api_keys = [api_keys]
                return ", ".join(api_keys)
        
            def save_keys_to_secrets(cfg_key, value):
                value = value.replace(" ", "")
                if value:
                    st.secrets["app"][cfg_key] = value.split(",")
        
            pexels_api_key = get_keys_from_secrets("pexels_api_keys")
            pexels_api_key = st.text_input(
                tr("Pexels API Key"), value=pexels_api_key, type="password"
            )
            save_keys_to_secrets("pexels_api_keys", pexels_api_key)
        
            pixabay_api_key = get_keys_from_secrets("pixabay_api_keys")
            pixabay_api_key = st.text_input(
                tr("Pixabay API Key"), value=pixabay_api_key, type="password"
            )
            save_keys_to_secrets("pixabay_api_keys", pixabay_api_key)



panel = st.columns(1)
main_panel = panel[0]

params = VideoParams(video_subject="")

with main_panel:
    with st.container(border=True):
        st.write(tr("Video Script Settings"))
        params.video_subject = st.text_input(
            tr("Video Subject"), value=st.session_state["video_subject"]
        ).strip()

        video_languages = [
            (tr("Auto Detect"), ""),
        ]
        for code in support_locales:
            video_languages.append((code, code))

        selected_index = st.selectbox(
            tr("Script Language"),
            index=0,
            options=range(len(video_languages)),  # 使用索引作为内部选项值
            format_func=lambda x: video_languages[x][0],  # 显示给用户的是标签
        )
        params.video_language = video_languages[selected_index][1]

        if st.button(
            tr("Generate Video Script and Keywords"), key="auto_generate_script"
        ):
            with st.spinner(tr("Generating Video Script and Keywords")):
                script = llm.generate_script(
                    video_subject=params.video_subject, language=params.video_language
                )
                terms = llm.generate_terms(params.video_subject, script)
                st.session_state["video_script"] = script
                st.session_state["video_terms"] = ", ".join(terms)

        params.video_script = st.text_area(
            tr("Video Script"), value=st.session_state["video_script"], height=280
        )
        if st.button(tr("Generate Video Keywords"), key="auto_generate_terms"):
            if not params.video_script:
                st.error(tr("Please Enter the Video Subject"))
                st.stop()

            with st.spinner(tr("Generating Video Keywords")):
                terms = llm.generate_terms(params.video_subject, params.video_script)
                st.session_state["video_terms"] = ", ".join(terms)

        params.video_terms = st.text_area(
            tr("Video Keywords"), value=st.session_state["video_terms"], height=50
        )
#################################################################################
        

        params.video_source = "pexels"
        st.secrets["video_source"] = params.video_source
        
        params.video_concat_mode = VideoConcatMode.random.value

        params.video_aspect = VideoAspect.landscape.value

        params.video_clip_duration = 3

        params.video_count = 1

        voices = voice.get_all_azure_voices(filter_locals=support_locales)
        saved_voice_name =  st.secrets.ui.get("voice_name", "")

        params.voice_name = saved_voice_name

        params.voice_volume = 1.0

        params.voice_rate = 1.0
        
        # 获取选择的背景音乐类型
        params.bgm_type = "random"

        params.bgm_volume = 0.2

        params.subtitle_enabled = True

        font_names = get_all_fonts()

        saved_font_name = st.secrets.ui.get("font_name", "")

        params.font_name = saved_font_name
        
        params.subtitle_position = "bottom"

        saved_text_fore_color = st.secrets.ui.get("text_fore_color", "")
        params.text_fore_color = saved_text_fore_color

        saved_font_size = st.secrets.ui.get("font_size", )
        params.font_size = saved_font_size

        params.stroke_color = "#000000"
        params.stroke_width = 1.5

video_button = st.button(tr("Generate Video"), use_container_width=True, type="primary")
image_button = st.button(tr("Generate Images"), use_container_width=True, type="primary")

if image_button:
    def split_paragraph(paragraph):
        # Step 1: Find all sentences ending with a full stop
        sentences = re.split(r'(?<=\.)\s+', paragraph.strip())
        
        # Step 2: Get the number of sentences
        num_sentences = len(sentences)
        
        # Step 3: Decide how many parts to split into based on the number of sentences
        if num_sentences < 6:
            return [" ".join(sentences[:])]  # Fewer than 4 sentences, return as one part
        elif num_sentences < 14:
            # Split into two parts
            mid = num_sentences // 2
            part1 = " ".join(sentences[:mid])
            part2 = " ".join(sentences[mid:])
            return [part1, part2]
        else:
            # Split into three parts
            part_size = num_sentences // 3
            part1 = " ".join(sentences[:part_size])
            part2 = " ".join(sentences[part_size:2*part_size])
            part3 = " ".join(sentences[2*part_size:])
            return [part1, part2, part3]
    paragraphs = split_paragraph(params.video_script)
    # Function to generate images using DALL-E
    def generate_image(prompt):
        url = "https://yescale.one/v1/images/generations"
        
        # Replace with your actual API token
        api_token = st.secrets.app.get(f"{llm_provider}_api_key", "")
        
        payload = {
            "prompt": prompt,
            "model": "dall-e-3",
            "n": 1,  # Generate three images
            "quality": "standard",
            "response_format": "url",
            "size": "1024x1024",
            "style": "vivid",
            "user": "user-1234"  
        }
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_token}"  # Add your API token here
        }

        # Sending the POST request
        response = requests.post(url, json=payload, headers=headers)

        # Check if the request was successful
        if response.status_code == 200:
            # Extract URLs from the response
            return [image['url'] for image in response.json()['data']]
        else:
            st.error(f"Error generating images: {response.text}")
            return []

    # Example usage in Streamlit
    with st.container(border=True):
        st.write("Image Generation")
        st.write("Generating images based on the video script...")
        image_urls = []
    # Generate images for each paragraph dynamically
    for paragraph in paragraphs:
        image_url = generate_image(paragraph)
        if image_url:
            image_urls.append(image_url)

    # Display the generated images in three columns
    if image_urls:
        cols = st.columns(len(paragraphs))  # Create three equal-width columns
        for col, url in zip(cols, image_urls):
            with col:
                st.image(url, use_column_width='auto')  # Use auto width for images
if video_button:
    # config.save_config()
    task_id = str(uuid4())
    if not params.video_subject and not params.video_script:
        st.error(tr("Video Script and Subject Cannot Both Be Empty"))
        scroll_to_bottom()
        st.stop()

    if llm_provider != "g4f" and not st.secrets.app.get(f"{llm_provider}_api_key", ""):
        st.error(tr("Please Enter the LLM API Key"))
        scroll_to_bottom()
        st.stop()

    if params.video_source not in ["pexels", "pixabay", "local"]:
        st.error(tr("Please Select a Valid Video Source"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pexels" and not st.secrets.app.get("pexels_api_keys", ""):
        st.error(tr("Please Enter the Pexels API Key"))
        scroll_to_bottom()
        st.stop()

    if params.video_source == "pixabay" and not st.secrets.app.get("pixabay_api_keys", ""):
        st.error(tr("Please Enter the Pixabay API Key"))
        scroll_to_bottom()
        st.stop()

    log_container = st.empty()
    log_records = []

    def log_received(msg):
        if st.secrets.ui["hide_log"]:
            return
        with log_container:
            log_records.append(msg)
            st.code("\n".join(log_records))

    logger.add(log_received)

    st.toast(tr("Generating Video"))
    logger.info(tr("Start Generating Video"))
    logger.info(utils.to_json(params))
    scroll_to_bottom()

    result = tm.start(task_id=task_id, params=params)
    if not result or "videos" not in result:
        st.error(tr("Video Generation Failed"))
        logger.error(tr("Video Generation Failed"))
        scroll_to_bottom()
        st.stop()

    video_files = result.get("videos", [])
    st.success(tr("Video Generation Completed"))
    try:
        if video_files:
            player_cols = st.columns(len(video_files) * 2 + 1)
            for i, url in enumerate(video_files):
                player_cols[i * 2 + 1].video(url)
    except Exception:
        pass

    open_task_folder(task_id)
    logger.info(tr("Video Generation Completed"))
    scroll_to_bottom()

# config.save_config()
