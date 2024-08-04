import os
import json
import logging
from flask import Flask, render_template, request, jsonify
import google.generativeai as genai
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options
import time
import asyncio

app = Flask(__name__)

# 로깅 설정
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Gemini API 설정
genai.configure(api_key="AIzaSyAkYsCWxjteASrgjxvoTAjc5qd1ot9yDW0")

generation_config = {
    "temperature": 1,
    "top_p": 0.95,
    "top_k": 64,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    generation_config=generation_config,
    system_instruction="당신은 사용자의 입력에서 중요한 키워드를 추출하고, 필요에 따라 적절한 키워드를 추천하는 모델입니다. 추출된 키워드와 추천된 키워드는 웹 크롤링 작업에 활용됩니다."
)

chat_session = model.start_chat(history=[])

def crawl_naver_map(query, target):
    chrome_options = Options()
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-position=-32000,-32000")

    driver = webdriver.Chrome(options=chrome_options)
    driver.set_window_size(1700, 1000)

    try:
        url = "https://map.naver.com/p?c=15.00,0,0,0,dh"
        driver.get(url)
        time.sleep(2)

        current_location = driver.find_element(By.XPATH, '//*[@id="app-layout"]/div[2]/div[1]/div[3]/div[1]/div/button')
        current_location.click()
        time.sleep(2)

        zoom_out = driver.find_element(By.XPATH, '//*[@id="app-layout"]/div[2]/div[1]/div[3]/div[2]/button[2]')
        zoom_out.click()
        time.sleep(1)

        input_button = driver.find_element(By.CLASS_NAME, 'input_search')
        input_button.send_keys(query)
        input_button.send_keys(Keys.ENTER)
        time.sleep(2)

        shop_dict = {}

        driver.switch_to.frame('searchIframe')
        temp = driver.find_elements(By.XPATH, '//*[@id="_pcmap_list_scroll_container"]/ul/li')

        for i in range(min(len(temp), 5)):  # 최대 5개의 가게만 크롤링
            information = {}
            
            shop = temp[i].find_element(By.XPATH, 'div[1]/a/div/div/span[1]')
            shop_name = shop.text
            shop.click()
            time.sleep(2)
            
            driver.switch_to.default_content()
            driver.switch_to.frame('entryIframe')
            
            if target == "menu":
                menu_button = driver.find_elements(By.CLASS_NAME, 'veBoZ')
                for s in range(len(menu_button)):
                    if menu_button[s].text == "메뉴":
                        menu_button[s].click()
                        break
                time.sleep(2)

                bb = driver.find_elements(By.CLASS_NAME, 'MXkFw')
                menu_list = list(map(lambda x: x.text, bb))
                
                images = driver.find_elements(By.CLASS_NAME, 'K0PDV')
                images = list(map(lambda x: x.get_attribute("src"), images))
                
                information["menu"] = menu_list
                information["menu_image"] = images[5:]

            elif target == "review":
                menu_button = driver.find_elements(By.CLASS_NAME, 'veBoZ')
                for s in range(len(menu_button)):
                    if menu_button[s].text == "리뷰":
                        menu_button[s].click()
                        break
                time.sleep(2)

                bb = driver.find_elements(By.CLASS_NAME, 'zPfVt')
                review_list = list(map(lambda x: x.text, bb))

                information["review"] = review_list
            
            shop_dict[shop_name] = information
            
            driver.switch_to.default_content()
            driver.switch_to.frame('searchIframe')

    except Exception as e:
        logger.error(f"Error during crawling: {str(e)}", exc_info=True)
    finally:
        driver.quit()

    return shop_dict

async def get_ai_response(user_input):
    try:
        response = await asyncio.wait_for(chat_session.send_message_async(user_input), timeout=10.0)
        return response
    except asyncio.TimeoutError:
        logger.error("AI response timeout")
        return None

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/chat', methods=['POST'])
async def chat():
    user_input = request.form['user_input']
    logger.debug(f"Received user input: {user_input}")
    
    try:
        response = await get_ai_response(user_input)
        if response is None:
            return jsonify({'error': 'AI response timeout', 'backup_response': '죄송합니다. 현재 응답을 생성할 수 없습니다.'})

        logger.debug(f"AI response: {response.text}")

        try:
            result = json.loads(response.text)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON response from model: {response.text}")
            return jsonify({'error': 'Invalid JSON response from model', 'raw_response': response.text})

        if result.get('entity') in ['menu', 'review']:
            crawl_results = crawl_naver_map(result.get('keyword', user_input), result['entity'])
            result['crawl_results'] = crawl_results

        return jsonify(result)
    except Exception as e:
        logger.error(f"Error occurred: {str(e)}", exc_info=True)
        return jsonify({'error': str(e)})

if __name__ == '__main__':
    app.run(debug=True)