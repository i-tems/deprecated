"""예시 일배치 ETL — 배포 검증용 레퍼런스 DAG.

extract → transform → load 3-task. KubernetesExecutor 라 각 task 는 별도 pod 에서
실행되므로 단계 간 데이터는 XCom 으로 전달한다(로컬 파일 공유 금지).
실 파이프라인은 이 패턴을 복제하되 source/sink 를 Airflow Connection 으로 주입한다.
"""
from __future__ import annotations

from datetime import datetime

from airflow import DAG
from airflow.operators.python import PythonOperator


def extract(**_):
    # 실제 구현에서는 Connection 으로 소스(DB/API/S3)에서 읽는다.
    return [1, 2, 3, 4, 5]


def transform(ti, **_):
    rows = ti.xcom_pull(task_ids="extract")
    return sum(rows)


def load(ti, **_):
    total = ti.xcom_pull(task_ids="transform")
    print(f"[load] daily total = {total}")


with DAG(
    dag_id="example_etl",
    description="배포 검증용 일배치 ETL 레퍼런스",
    start_date=datetime(2026, 5, 1),
    schedule="@daily",
    catchup=False,
    tags=["example", "etl"],
) as dag:
    t_extract = PythonOperator(task_id="extract", python_callable=extract)
    t_transform = PythonOperator(task_id="transform", python_callable=transform)
    t_load = PythonOperator(task_id="load", python_callable=load)

    t_extract >> t_transform >> t_load
