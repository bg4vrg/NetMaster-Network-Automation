# === NetMaster 后台账号创建工具 ===
import sqlite3
from werkzeug.security import generate_password_hash
import os

DB_NAME = 'net_assets.db'

def create_user(username, password):
    if not os.path.exists(DB_NAME):
        print("❌ 错误：找不到数据库文件，请先运行一次 run_server.py 初始化系统！")
        return

    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        
        # 使用与主程序相同的加密算法对密码进行 Hash 处理
        p_hash = generate_password_hash(password)
        
        c.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, p_hash))
        conn.commit()
        print(f"\n🎉 成功！已为同事创建专属账号：【{username}】")
        
    except sqlite3.IntegrityError:
        print(f"\n⚠️ 失败：用户名【{username}】已经存在，请换一个名字。")
    except Exception as e:
        print(f"\n❌ 数据库写入报错: {e}")
    finally:
        conn.close()

if __name__ == '__main__':
    print("="*40)
    print("🛡️ NetMaster 后台账号创建向导")
    print("="*40)
    
    while True:
        u = input("\n👤 请输入同事的新用户名 (输入 q 退出): ").strip()
        if u.lower() == 'q':
            break
        if not u:
            print("用户名不能为空！")
            continue
            
        p = input("🔑 请设置初始密码: ").strip()
        if not p:
            print("密码不能为空！")
            continue
            
        create_user(u, p)