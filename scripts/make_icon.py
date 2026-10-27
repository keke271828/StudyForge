from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

root = Path(__file__).resolve().parent.parent
target = root / 'desktop' / 'assets'
target.mkdir(parents=True, exist_ok=True)
image = Image.new('RGBA', (512, 512))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((16, 16, 496, 496), radius=112, fill='#173b36')
font = ImageFont.truetype('C:/Windows/Fonts/timesbd.ttf', 352)
bounds = draw.textbbox((0, 0), 'Σ', font=font)
draw.text(((512 - bounds[2] + bounds[0]) / 2 - bounds[0],
           (512 - bounds[3] + bounds[1]) / 2 - bounds[1] - 8), 'Σ', font=font, fill='#b8eed3')
image.save(target / 'studyforge.png')
image.save(target / 'studyforge.ico', sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
