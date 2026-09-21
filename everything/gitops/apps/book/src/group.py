from functions import get_config, get_output_dir
class Groupper():
    def __init__(self, book_id):
        self.book_id = book_id
        self.text_output_dir = get_output_dir(book_id, "text")
        self.groups_output_dir = get_output_dir(book_id, "groups")

    def group(self, groups):
        for index, group in enumerate(groups):
            start_page = group["start_page"]
            end_page = group["end_page"]
            name = group["name"]
            print(f"📖 {name} ({start_page} - {end_page})")
            group_text = ""
            
            for page_id in range(start_page, end_page + 1):

                text_path = f"{self.text_output_dir}/{page_id}.txt"
                with open(text_path, "r") as f:
                    text = f.read()
                    group_text += text + "\n"

            with open(f"{self.groups_output_dir}/{index}.txt", "w") as f:
                f.write(group_text)
