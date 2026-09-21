from concurrent.futures import ThreadPoolExecutor
from tqdm import tqdm
from functions import get_llm_provider, get_output_dir
import json
import os

class LLMProcessor():
    def __init__(self, book_id, types, update_types):
        self.book_id = book_id
        self.types = set(types)
        self.update_types = set(update_types)
        self.llm_client, self.model = get_llm_provider(book_id)
        self.llm_output_dir = get_output_dir(book_id, "llm")
        self.llm_text_output_dir = get_output_dir(book_id, "llm_text")
        self.groups_output_dir = get_output_dir(book_id, "groups")
        self.text_output_dir = get_output_dir(book_id, "text")

    def update_key(self, group_id, key, processor):

        before_llm_json = self.load_llm_json(group_id)
        group_text = self.load_text(group_id)
        if key in self.types:
            if key in self.update_types or key not in before_llm_json:
                value = processor(group_text)
            else:
                value = before_llm_json[key]
            self.save_llm_json(group_id, key, value)

    def process_file(self, group_id):
        self.update_key(group_id, "long_summary", self.process_long_summary)
        self.update_key(group_id, "short_summary", self.process_short_summary)
        self.update_key(group_id, "translated", self.process_translate)

    def load_text(self, group_id):
        with open(f"{self.groups_output_dir}/{group_id}.txt", "r") as f:
            group_text = f.read()
        return group_text

    def load_llm_json(self, group_id):
        group_file_path = f"{self.llm_output_dir}/{group_id}.json"
        before_group_data = {}
        if os.path.exists(group_file_path):
            with open(group_file_path, "r") as fp:
                before_group_data = json.loads(fp.read())
        return before_group_data

    def save_llm_json(self, group_id, key, value):
        llm_json = self.load_llm_json(group_id)
        with open(f"{self.llm_output_dir}/{group_id}.json", "w") as fp:
            llm_json[key] = value
            fp.write(json.dumps(llm_json, ensure_ascii=False, indent=4))


    # def process_translate_by_page(self, page_filename):
    #     with open(f"{self.text_output_dir}/{page_filename}", "r") as f:
    #         page_text = f.read()
    #         prompt = f"""
    #         다음은 책의 한 부분입니다. 알아듣기 쉽게 한국어로 정리하세요.
    #         1. 한국어(존댓말)를 사용하세요.
    #         2. 이해하기 쉽게 예시나, 부가 설명을 붙일 수 있습니다.
    #         3. markdown으로 생성하세요. markdown으로 생성할 때 #(h1), ##(h2)는 사용하지 마세요. 중간제목은 ###으로 표현하세요. 그보다 큰 제목은 "절대로" 사용하지 마세요.
    #         4. 내용이 짧다면 짧게 생성합니다.
    #         """

    #         messages = [{
    #             "role": "system",
    #             "content": prompt
    #         }, {
    #             "role": "user",
    #             "content": f"{page_text}"
    #         }]

    #         response = self.openai_client.chat.completions.create(
    #             model="gpt-4o-mini",
    #             messages=messages,
    #         )
    #         translated = response.choices[0].message.content
    #         with open(f"{self.llm_text_output_dir}/{page_filename}.json", "w") as fp:
    #             fp.write(json.dumps({
    #                 "translated": translated
    #             }, ensure_ascii=False, indent=4))


    def process_long_summary(self, group_text: str):

        prompt = """
You will be transforming a book chapter into a comprehensive Korean blog post that captures all the valuable content from the chapter. The goal is to create a blog post that allows readers to understand the chapter's content without reading the original.

Here is the chapter you need to work with:

<chapter>
{{CHAPTER}}
</chapter>

Please follow these requirements carefully:

**Content Requirements:**
- Create a long, detailed summary that is comprehensive enough for readers to fully understand the chapter without reading the original
- The content should be sufficiently long and detailed - do not create a brief summary
- Include all important concepts, ideas, and information from the chapter
- Use interpretation (의역) over literal translation when it makes the content clearer and more natural in Korean

**Structure Requirements:**
- Begin with a section titled "개요" (Overview)
- End with a section titled "결론" (Conclusion)
- Organize the content with appropriate intermediate sections between the overview and conclusion
- The chapter may have headings marked with #, ##, or ###, but note that these markings may not be consistently hierarchical

**Markdown Formatting Requirements:**
- Use markdown format for the entire blog post
- **NEVER use # (h1) or ## (h2) headings**
- Use only ### (h3) and #### (h4) for all section headings
- Do not use any heading levels larger than ### (h3)
- Use other markdown features (bold, italic, lists, etc.) as appropriate

**Language Requirements:**
- Write entirely in Korean
- Use formal, polite language (존댓말)
- Keep technical terms and proper nouns in their original form (e.g., "AI", "GPT-4", "ChatGPT", "Transformer", etc.)

Write your blog post now, ensuring it is comprehensive, well-structured, and follows all the formatting guidelines above.
        """

        messages = [{
            "role": "system",
            "content": prompt
        }, {
            "role": "user",
            "content": f"{group_text}"
        }]

        long_summary = self.llm_client.chat_completion(messages, self.model)
        return long_summary
    
    def process_short_summary(self, group_text: str):
        short_summary_prompt = """
You will be summarizing content written in Korean. Your task is to create a concise yet comprehensive summary that captures the essential information and main message of the original content.

Here is the content to summarize:

<content>
{{CONTENT}}
</content>

Please create a summary following these formatting requirements:

Summary Format:
- Begin with a 2-3 line paragraph that summarizes the core content, making it easy to understand what the text is about
- If necessary, you may add bullet points (using •) to list additional key points

Writing Rules:
1. Write in Korean using formal polite language (ending sentences with ~습니다, ~입니다)
2. Keep technical terms and proper nouns in their original form (e.g., "AI", "GPT-4", "ChatGPT", "Machine Learning", etc.)
3. Use natural paraphrasing rather than literal translation to make the content easy to understand
4. Focus on accurately conveying the core message and key information from the original content
5. Maintain objectivity and do not add information that is not present in the original content

Write your summary inside <summary> tags.
        """

        messages = [{
            "role": "system",
            "content": short_summary_prompt
        }, {
            "role": "user",
            "content": f"{group_text}"
        }]

        short_summary = self.llm_client.chat_completion(messages, self.model)
        return short_summary
    
    def process_translate(self, group_text: str):
        translate_prompt = """
You will be rewriting and translating text into natural, fluent Korean. The text you receive may have been extracted via OCR, so it might contain errors or awkward phrasing that you should correct.

Here is the text to process:

<text>
{{TEXT}}
</text>

Your task is to rewrite all content from the text above into smooth, natural Korean that is easy for readers to understand. Follow these rules carefully:

1. **Natural Korean Expression**: Ensure the flow of sentences is smooth and uses expressions that Korean readers will find natural and easy to understand.

2. **Technical Terms**: Keep technical terms in their original form if commonly used that way in Korean, or adapt them naturally to match Korean conventions and idiomatic expressions.

3. **Translation Approach**: Prioritize natural meaning over literal translation. Use liberal translation (의역) when it makes the text more readable and natural in Korean.

4. **OCR Error Correction**: Since the text was extracted via OCR, it may contain errors, awkward phrasing, or broken sentences. Correct these errors, supplement missing information where context makes it clear, and remove problematic sections as needed.

5. **Completeness**: Process every sentence in the input text. Do not skip or omit any content.

6. **Markdown Format**: Return your output in markdown format. Preserve any existing markdown structures like:
   - Images: Keep image file paths exactly as they are - DO NOT modify image paths under any circumstances
   - Code blocks: Wrap code in proper markdown code formatting (using backticks or code fences)
   - Tables: Convert tables into proper markdown table format
   - Lists and bullets: If bullet points or list structures are awkward, restructure them to be properly formatted markdown lists

7. **Structure Normalization**: If markdown syntax appears broken or awkward (such as malformed bullets or headers), restructure it into proper, well-formed markdown.

Write your complete Korean translation inside <translation> tags. Ensure all content is translated and properly formatted in markdown.
        """

        messages = [{
            "role": "system",
            "content": translate_prompt
        }, {
            "role": "user",
            "content": f"{group_text}"
        }]

        translated = self.llm_client.chat_completion(messages, self.model)
        return translated

    def process(self, groups, max_workers):
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            group_ids = [p.split(".")[0] for p in sorted(os.listdir(self.groups_output_dir), key=lambda x: int(x.split(".")[0]))]
            list(tqdm(executor.map(self.process_file, group_ids), total=len(group_ids), desc="Processing files"))
        
        

        # if "translate_by_page" in self.types:

        #     target_page_filenames = []
        #     for page_filename in tqdm(os.listdir(self.text_output_dir)):
        #         if os.path.isfile(f"{self.llm_text_output_dir}/{page_filename}.json"):
        #             continue
        #         target_page_filenames.append(page_filename)

        #         continue

        #     print(f"target_page_filenames: {target_page_filenames}")
        #     with ThreadPoolExecutor(max_workers=4) as executor:
        #         list(tqdm(executor.map(self.process_translate_by_page, target_page_filenames), total=len(target_page_filenames), desc="Processing files"))

        #     for group_id, group in enumerate(groups):
        #         page_translateds = []
        #         for page in range(group["start_page"], group["end_page"] + 1):
        #             with open(f"{self.llm_text_output_dir}/{page}.txt.json", "r") as f:
        #                 page_json = json.loads(f.read())
        #                 page_translated = page_json["translated"]
        #                 page_translateds.append({
        #                     "page_translated": page_translated,
        #                     "page_name": page_translated.split("\n")[0],
        #                 })
                    
        #         with open(f"{self.llm_output_dir}/{group_id}.json", "r") as f:
        #             data = json.loads(f.read())

        #         data["translate_by_page"] = page_translateds

        #         with open(f"{self.llm_output_dir}/{group_id}.json", "w") as f:
        #             f.write(json.dumps(data, ensure_ascii=False, indent=4))
