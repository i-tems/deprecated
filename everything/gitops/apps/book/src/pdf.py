from marker.convert import convert_single_pdf
from marker.models import load_all_models
from functions import get_output_dir, get_config

class PDFParser():
    def __init__(self, book_id):
        self.book_id = book_id
        self.marker_output_dir = get_output_dir(self.book_id, "marker")
        self.view_output_dir = get_output_dir(self.book_id, "view")

    def convert(self):
        model_lst = load_all_models()

        text, images, metadata = convert_single_pdf(
            f"source/{self.book_id}.pdf",
            model_lst
        )

        with open(f"{self.marker_output_dir}/text.md", "w") as f:
            f.write(text)

        for image_name in images:
            images[image_name].save(f"{self.view_output_dir}/{image_name}")

    def split_result(self):
        text_output_dir = get_output_dir(self.book_id, "text")
        group_split_by = get_config(self.book_id, "group_split_by")
        # text_split_by = get_config(self.book_id, "text_split_by")
        groups = []
        with open(f"{self.marker_output_dir}/text.md", "r") as f:
            md_text = f.read()
            
        rows = []
        split_text_number = 0
        splited = []
        for p in md_text.split("\n"):
            rows.append(p)

            if p.startswith("#"):
                splited.append({
                    "id": split_text_number,
                    "rows": rows[:-1].copy(),
                })
                rows = [rows[-1]]
                split_text_number += 1

        if len(rows):
            splited.append({
                "id": split_text_number,
                "rows": rows.copy(),
            })


        before_index = 0
        before_group_row = "## About"
        for index, split in enumerate(splited):
            with open(f"{text_output_dir}/{split['id']}.txt", "w") as f:
                f.write("\n".join(split['rows']))
            
            for row in split["rows"]:
                if row.find(group_split_by) == -1:
                    continue

                groups.append({
                    "start_page": before_index,
                    "end_page": index - 1,
                    "name": before_group_row,
                })
                before_index = index
                before_group_row = row

        groups.append({
            "start_page": before_index,
            "end_page": index,
            "name": before_group_row,
        })
        
        return groups
