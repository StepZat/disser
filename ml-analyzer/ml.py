import os
from contextlib import asynccontextmanager

import pandas as pd
import uvicorn
from dotenv import load_dotenv
from pymongo.errors import OperationFailure
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score
import pickle
import asyncio
from motor.motor_asyncio import AsyncIOMotorClient
from fastapi import FastAPI
from datetime import datetime

# === Загрузка переменных окружения из .env ===
load_dotenv()

# === Конфигурация MongoDB из .env ===
MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
DB_NAME = os.getenv("MONGO_DB", "logstash_db")
COLLECTION_NAME = os.getenv("MONGO_COLLECTION", "dhcp_logs")

MONGO_URI = f"mongodb://{MONGO_HOST}:{MONGO_PORT}"

# === Контекст lifespan для FastAPI ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск задачи классификации при старте
    task = asyncio.create_task(classify_logs())
    yield
    # Остановка задачи при завершении
    task.cancel()
# === FastAPI приложение с единственным /health endpoint ===
app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health():
    """
    Простая проверка работоспособности (liveness).
    """
    return {"status": "up", "timestamp": datetime.now()}

# === Функция для обучения модели ===
def train_model(train_file):
    # Загрузка тренировочной выборки
    df = pd.read_csv(train_file, sep=';')
    X_train = df["info_message"].values
    y_train = df["message_type"].values

    # Векторизация текста
    vect = CountVectorizer(analyzer='word')
    X_train_vect = vect.fit_transform(X_train)

    # Обучение модели
    clf = RandomForestClassifier(n_estimators=30, n_jobs=-1)
    clf.fit(X_train_vect, y_train)

    # Сохранение модели и векторизатора
    with open("model.pkl", "wb") as model_file:
        pickle.dump(clf, model_file)
    with open("vectorizer.pkl", "wb") as vect_file:
        pickle.dump(vect, vect_file)

    print("Модель и векторизатор сохранены.")


# === Функция для классификации тестового набора данных ===
def test_model(test_file):
    # Загрузка модели и векторизатора
    with open("model.pkl", "rb") as model_file:
        clf = pickle.load(model_file)
    with open("vectorizer.pkl", "rb") as vect_file:
        vect = pickle.load(vect_file)

    # Загрузка тестовых данных
    df_test = pd.read_csv(test_file, sep=';')
    X_test = df_test["info_message"].values
    y_test = df_test["message_type"].values

    # Векторизация тестовых данных
    X_test_vect = vect.transform(X_test)

    # Предсказание на тестовых данных
    y_pred = clf.predict(X_test_vect)

    # Расчет accuracy
    acc = accuracy_score(y_test, y_pred)
    print(f"Точность модели на тестовых данных: {acc:.4f}")


# === Функция классификации логов ===
async def classify_logs():
    # Загрузка модели и векторизатора
    with open("model.pkl", "rb") as mf, open("vectorizer.pkl", "rb") as vf:
        clf = pickle.load(mf)
        vect = pickle.load(vf)

    # Подключение к MongoDB
    client = AsyncIOMotorClient(MONGO_URI)
    db = client[DB_NAME]
    coll = db[COLLECTION_NAME]

    async with coll.watch() as stream:
        async for change in stream:
            if change.get("operationType") != "insert":
                continue
            doc = change.get("fullDocument", {})

            # Удаляем документы без Info_message
            if "Info_message" not in doc:
                await coll.delete_one({"_id": doc.get("_id")})
                continue

            # Классификация и запись результата
            msg = doc["Info_message"]
            pred = clf.predict(vect.transform([msg]))[0]
            await coll.update_one(
                {"_id": doc["_id"]},
                {"$set": {"predicted_message_type": pred}}
            )
            print(f"[{datetime.now()}] Doc {doc.get('_id')} → {pred}")


# === Основной блок вызова ===
if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8002)

