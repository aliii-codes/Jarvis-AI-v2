import asyncio
from random import randint
from PIL import Image
import requests
from dotenv import get_key
import os
from time import sleep


API_URL = "https://api-inference.huggingface.co/models/stabilityai/stable-diffusion-xl-base-1.0"
HEADERS = {"Authorization": f"Bearer {get_key('.env', 'HuggingFaceAPIKey')}"}

# Function to open saved images
def open_images(prompt):
    folder_path = r"Data"
    prompt = prompt.replace(' ', '_')
    files = [f"{prompt}{i}.jpg" for i in range(1, 5)]

    for jpg_file in files:
        image_path = os.path.join(folder_path, jpg_file)

        try:
            img = Image.open(image_path)
            print(f"Opening image: {image_path}")
            img.show()
            sleep(1)
        except IOError:
            print(f" Unable to open: {image_path}")


async def query(payload):
    print(f"Sending prompt to API: {payload['inputs']}")
    response = await asyncio.to_thread(requests.post, API_URL, headers=HEADERS, json=payload)

    try:
        content_type = response.headers.get("Content-Type", "")
        if "application/json" in content_type:
            error_data = response.json()
            print(f" API Error JSON: {error_data}")
            return b""
    except Exception as e:
        print(f" Error decoding API response: {e}")

    if response.status_code != 200:
        print(f"[{response.status_code}]: {response.text}")
        return b""

    return response.content


async def generate_images(prompt: str):
    tasks = []
    for _ in range(4):
        payload = {
            "inputs": f"{prompt}, 4K, ultra detailed, masterpiece, high resolution, seed={randint(0, 1000000)}",
        }
        task = asyncio.create_task(query(payload))
        tasks.append(task)

    image_bytes_list = await asyncio.gather(*tasks)

    for i, image_bytes in enumerate(image_bytes_list):
        if not image_bytes:
            print(f"⚠️ Skipping image {i+1} due to empty response.")
            continue

        filename = f"Data/{prompt.replace(' ', '_')}{i + 1}.jpg"
        with open(filename, "wb") as f:
            f.write(image_bytes)
        print(f"✅ Saved: {filename}")


def GenerateImages(prompt: str):
    asyncio.run(generate_images(prompt))
    open_images(prompt)

while True:
    try:
        with open(r"Frontend/Files/Imagegeneration.data", "r") as f:
            data: str = f.read().strip()

        if not data:
            sleep(1)
            continue

        Prompt, Status = map(str.strip, data.split(","))

        if Status.lower() == "true":
            print("🚀 Generating images...")
            GenerateImages(prompt=Prompt)

            with open(r"Frontend/Files/Imagegeneration.data", "w") as f:
                f.write("False,False")
            break
        else:
            sleep(1)
    except Exception as e:
        pass