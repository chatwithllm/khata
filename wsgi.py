from dotenv import load_dotenv

from khata import create_app

load_dotenv()
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, port=5050)
