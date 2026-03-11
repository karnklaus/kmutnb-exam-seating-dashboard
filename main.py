#!/usr/bin/env python3
"""
main.py - ตัวอย่างสคริปต์ Python เล็กๆ พร้อม CLI

ใช้งาน:
  python main.py            # พิมพ์ "สวัสดี, โลก!"
  python main.py -n Alice   # พิมพ์ "สวัสดี, Alice!"
  python main.py -n Bob -c 3  # พิมพ์ 3 ครั้ง
"""

import argparse


def main():
    parser = argparse.ArgumentParser(description="สคริปต์ตัวอย่างสำหรับทักทาย")
    parser.add_argument("--name", "-n", default="โลก", help="ชื่อเพื่อทักทาย (default: โลก)")
    parser.add_argument("--count", "-c", type=int, default=1, help="จำนวนครั้งในการพิมพ์")
    args = parser.parse_args()

    for _ in range(max(0, args.count)):
        print(f"สวัสดี, {args.name}!")


if __name__ == "__main__":
    main()
