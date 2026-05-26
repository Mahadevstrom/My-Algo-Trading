import json
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.models.strategy import CustomStrategy, StrategyCreate

router = APIRouter(prefix="/api/strategies", tags=["strategies"])


@router.get("")
def list_strategies(db: Session = Depends(get_db)) -> list[dict]:
    items = list(db.scalars(select(CustomStrategy).order_by(CustomStrategy.name)))
    results = []
    for item in items:
        try:
            cfg = json.loads(item.config_json)
        except Exception:
            cfg = {}
        results.append({
            "id": item.id,
            "name": item.name,
            "description": item.description,
            "config": cfg,
            "created_at": item.created_at,
            "updated_at": item.updated_at
        })
    return results


@router.get("/{strategy_id}")
def get_strategy(strategy_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(CustomStrategy, strategy_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found.")
    try:
        cfg = json.loads(item.config_json)
    except Exception:
        cfg = {}
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "config": cfg,
        "created_at": item.created_at,
        "updated_at": item.updated_at
    }


@router.post("", status_code=status.HTTP_201_CREATED)
def create_strategy(payload: StrategyCreate, db: Session = Depends(get_db)) -> dict:
    existing = db.scalar(select(CustomStrategy).where(CustomStrategy.name == payload.name.strip()))
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Strategy with name '{payload.name}' already exists."
        )
    
    item = CustomStrategy(
        name=payload.name.strip(),
        description=payload.description.strip() if payload.description else None,
        config_json=json.dumps(payload.config)
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "config": payload.config,
        "created_at": item.created_at,
        "updated_at": item.updated_at
    }


@router.put("/{strategy_id}")
def update_strategy(strategy_id: int, payload: StrategyCreate, db: Session = Depends(get_db)) -> dict:
    item = db.get(CustomStrategy, strategy_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found.")
        
    existing = db.scalar(
        select(CustomStrategy)
        .where(CustomStrategy.name == payload.name.strip(), CustomStrategy.id != strategy_id)
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Another strategy with name '{payload.name}' already exists."
        )
        
    item.name = payload.name.strip()
    item.description = payload.description.strip() if payload.description else None
    item.config_json = json.dumps(payload.config)
    db.commit()
    db.refresh(item)
    return {
        "id": item.id,
        "name": item.name,
        "description": item.description,
        "config": payload.config,
        "created_at": item.created_at,
        "updated_at": item.updated_at
    }


@router.delete("/{strategy_id}")
def delete_strategy(strategy_id: int, db: Session = Depends(get_db)) -> dict:
    item = db.get(CustomStrategy, strategy_id)
    if item is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Strategy not found.")
    db.delete(item)
    db.commit()
    return {"ok": True, "message": "Strategy deleted successfully."}
