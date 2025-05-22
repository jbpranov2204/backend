from flask import Flask, request, jsonify
from flask_cors import CORS
import psycopg2
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
import requests
import json

# Configure logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

app = Flask(__name__)
CORS(app)  # Enable CORS for Flutter frontend

# Database configuration
DB_CONFIG = {
    'dbname': os.getenv('DB_NAME', 'llm_postgres'),
    'user': os.getenv('DB_USER', 'postgres'),
    'password': os.getenv('DB_PASSWORD', 'postgres'),
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432')
}

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_API_URL = os.getenv("GEMINI_API_URL")


def get_db_connection():
    try:
        logger.debug(f"Attempting to connect to database with config: {DB_CONFIG}")
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except psycopg2.Error as e:
        logger.error(f"Database connection error: {e}")
        raise

# Initialize database table
def init_db():
    conn = None
    cur = None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        
        # Create table
        cur.execute('''
            CREATE TABLE IF NOT EXISTS prompts (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL,
                query TEXT NOT NULL,
                casual_response TEXT NOT NULL,
                formal_response TEXT NOT NULL,
                blended_response TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        conn.commit()
        print("table created successfully!")
    except Exception as e:
        print(f"Error creating table: {e}")
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

init_db()

def get_gemini_response(query, style):

    full_url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
    try:
        
        if style == "casual":
            prompt = "Respond in a casual and creative way"
        elif style == "formal":
            prompt = "Provide a formal response shortly"
        else:
            prompt = "Respond as a blend of both casual and formal styles"
        
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"{prompt} to this query: {query}"
                }]
            }]
        }
        
        response = requests.post(
            full_url,
            headers={'Content-Type': 'application/json'},
            json=payload
        )
        
        if response.status_code == 200:
            result = response.json()
            return result['candidates'][0]['content']['parts'][0]['text']
        else:
            logger.error(f"Gemini API error: {response.text}")
            return None
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}")
        return None

@app.route('/prompt', methods=['POST'])
def create_prompt():
    try:
        data = request.json
        logger.debug(f"Received POST request with data: {data}")
        
        if not data or not all(k in data for k in ['user_id', 'query']):
            return jsonify({'error': 'Missing required fields'}), 400
        
        # Get responses from Gemini API
        casual_response = get_gemini_response(data['query'], "casual")
        formal_response = get_gemini_response(data['query'], "formal")
        blended_response = get_gemini_response(data['query'], "both")

        if not casual_response or not formal_response or not blended_response:
            return jsonify({'error': 'Failed to get AI response'}), 500
        
        conn = None
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute('''
                INSERT INTO prompts (user_id, query, casual_response, formal_response, blended_response)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            ''', (data['user_id'], data['query'], casual_response, formal_response, blended_response))

            new_id = cur.fetchone()[0]
            conn.commit()
            cur.close()
            
            # Include AI responses in the API response
            return jsonify({
                'id': new_id,
                'casual_response': casual_response,
                'formal_response': formal_response,
                'blended_response': blended_response
            })
        except Exception as e:
            logger.error(f"Database error: {e}")
            return jsonify({'error': str(e)}), 500
        finally:
            if conn:
                conn.close()
                
    except Exception as e:
        logger.error(f"Server error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/prompt', methods=['GET'])
def get_prompts():
    user_id = request.args.get('user_id')
    if not user_id:
        return jsonify({'error': 'Missing user_id parameter'}), 400
    
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute('''
        SELECT id, query, casual_response, formal_response, blended_response, created_at
        FROM prompts
        WHERE user_id = %s
        ORDER BY created_at DESC
    ''', (user_id,))
    
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    prompts = [{
        'id': row[0],
        'query': row[1],
        'casual_response': row[2],
        'formal_response': row[3],
        'blended_response': row[4],
        'created_at': row[5].isoformat()
    } for row in rows]

    return jsonify(prompts)

if __name__ == '__main__':
    print("Starting Flask server on http://localhost:8000")
    try:
        init_db()
        app.run(host='0.0.0.0', port=8000, debug=True)
    except Exception as e:
        print(f"Error starting server: {e}")