import pyautogui
import time
from tqdm import tqdm
import random
import os
import subprocess
import json
from functions import get_config, get_output_dir
from PIL import Image, ImageEnhance, ImageFilter
import pytesseract
import cv2
import numpy as np

class Kindle():
    def __init__(self, book_id):
        self.book_id = book_id
        self.kindle_images_dir = get_output_dir(self.book_id, 'kindle_images')
        self.kindle_cropped_dir = get_output_dir(self.book_id, 'kindle_cropped')
        self.text_dir = get_output_dir(self.book_id, 'text')
    
    def get_kindle_window_id(self):
        result = subprocess.run(
            ["yabai", "-m", "query", "--windows"],
            capture_output=True,
            text=True,
            check=True
        )
        windows = json.loads(result.stdout)

        for win in windows:
            if win.get("app") == "Kindle":
                return win.get("id")
        if not windows:
            raise Exception("😱 Kindle 윈도우를 찾을 수 없습니다.")

    def capture_window(self, window_id, output_path):
        subprocess.run(
            ["screencapture", "-l", str(window_id), output_path],
            check=True
        )

    def collect_images(self):
        total_page = get_config(self.book_id, "total_page")

        window_id = self.get_kindle_window_id()
        print(f"✅ Kindle 윈도우 ID: {window_id}")
        print(f"📚 {self.book_id} 페이지 수: {total_page}")

        wait_time = 10
        for i in list(range(1, wait_time + 1)):
            print(f"⏳ {wait_time - i + 1} 초 남았습니다. Kindle 윈도우를 활성화하세요.")
            time.sleep(1)

        for page_id in tqdm(list(range(1, total_page + 1))):
            output_file = os.path.expanduser(f"{self.kindle_images_dir}/{page_id}.png")

            self.capture_window(window_id, output_file)
            pyautogui.press('right')
            time.sleep(random.randint(10, 10) / 10)

    def crop_images(self):
        with open(f"config/{self.book_id}.json", "r") as fp:
            book_config = json.loads(fp.read())
            top_crop = book_config["top_crop"]
            bottom_crop = book_config["bottom_crop"]

        kindle_image_filenames = []
        for image_filename in os.listdir(self.kindle_images_dir):
            if image_filename.startswith("."):
                continue

            kindle_image_filenames.append(image_filename)


        for image_filename in tqdm(sorted(kindle_image_filenames, key=lambda x: int(x.split(".")[0]))):
            page_id = int(image_filename.split(".")[0])
            image_path = f"{self.kindle_images_dir}/{image_filename}"
            cropped_image_path = f"{self.kindle_cropped_dir}/{page_id}.png"

            image = Image.open(image_path)

            width, height = image.size

            cropped_image = image.crop((0, top_crop, width, height - bottom_crop))

            cropped_image.save(cropped_image_path)

    def preprocess_image(self, image):
        """이미지 전처리로 OCR 품질 향상"""
        # PIL Image를 numpy array로 변환
        img_array = np.array(image)

        # 그레이스케일 변환
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array

        # 노이즈 제거 (Gaussian Blur)
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)

        # 대비 향상 (CLAHE - Contrast Limited Adaptive Histogram Equalization)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        enhanced = clahe.apply(denoised)

        # 이진화 (Adaptive Thresholding) - 다양한 조명 조건에 강함
        binary = cv2.adaptiveThreshold(
            enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY, 11, 2
        )

        # 모폴로지 연산으로 텍스트 선명도 향상
        kernel = np.ones((1, 1), np.uint8)
        morph = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

        # numpy array를 PIL Image로 다시 변환
        return Image.fromarray(morph)

    def ocr_images(self):
        with open(f"config/{self.book_id}.json", "r") as fp:
            book_config = json.loads(fp.read())
            lang = book_config["lang"]

        # Tesseract 설정 최적화
        custom_config = r'--oem 1 --psm 6'  # LSTM OCR 엔진 + 단일 텍스트 블록으로 가정

        for image_filename in tqdm(sorted(os.listdir(self.kindle_cropped_dir), key=lambda x: int(x.split(".")[0]))):
            page_id = int(image_filename.split(".")[0])
            image_path = f"{self.kindle_cropped_dir}/{image_filename}"
            result_path = f"{self.text_dir}/{page_id}.txt"
            if os.path.exists(result_path):
                print(f"✅ {result_path} exists. Skip.")
                continue

            # 이미지 열기
            img = Image.open(image_path)

            # 전처리 적용
            preprocessed_img = self.preprocess_image(img)

            # Tesseract OCR 실행 (최적화된 설정 사용)
            text = pytesseract.image_to_string(preprocessed_img, lang=lang, config=custom_config)

            with open(result_path, "w") as f:
                f.write(text)