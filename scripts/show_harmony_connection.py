"""在本机临时窗口显示手机连接码；凭据及图片只在内存，不输出/保存。"""
import json
from pathlib import Path
import time

from dashboard_api.mobile_access import load_token


def main():
    import tkinter as tk
    import qrcode
    from PIL import ImageTk

    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / 'runtime/harmony-access/access.json').read_text(encoding='utf-8'))
    base = config['api_base_url']
    if not base.startswith('https://'):
        raise ValueError('https_required')
    payload = json.dumps({'type': 'reops-mobile-connection-v1', 'base_url': base,
                         'token': load_token(), 'expires_at': int((time.time() + 180) * 1000)},
                        separators=(',', ':'))
    code = qrcode.QRCode(box_size=7, border=4)
    code.add_data(payload)
    code.make(fit=True)
    payload = None
    window = tk.Tk()
    window.title('ReOps 手机连接（私密窗口，请勿截图或录屏）')
    window.attributes('-topmost', True)
    tk.Label(window, text='手机 ReOps → 连接 → 扫描电脑连接码', font=('Microsoft YaHei', 14)).pack(padx=20, pady=10)
    picture = ImageTk.PhotoImage(code.make_image().convert('RGB'))
    tk.Label(window, image=picture).pack(padx=15)
    tk.Label(window, text=f'核对手机地址：{base}\n此码含只读凭据，请勿截图、分享或录屏。\n连接信息仅限当前 App 会话；窗口180秒后关闭。',
             font=('Microsoft YaHei', 11)).pack(padx=15, pady=10)
    tk.Button(window, text='已扫码，关闭私密窗口', command=window.destroy).pack(pady=8)
    window.after(180000, window.destroy)
    window.mainloop()


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('连接码窗口未能打开；未输出凭据或原始异常。')
        raise SystemExit(1) from None
