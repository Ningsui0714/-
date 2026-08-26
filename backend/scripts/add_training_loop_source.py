"""
给「PyTorch 训练循环入门」项目添加本地参考资料（讲义 + 练习代码）。

- 添加 file 类型 source，指向 data/course-materials/pytorch-training-loop/
- 处理生成 chunks（自动切块）
- 按 checkpoint 内容主题把 chunks 关联到对应关卡

用法: cd backend && venv/bin/python scripts/add_training_loop_source.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import select
from app.db.database import async_session, init_db
from app.core.config import settings
from app.models.project import Project, Source, Roadmap, Checkpoint, CheckpointChunk, Chunk
from app.services.chunker import SourceProcessor

MATERIALS_DIR = "data/course-materials/pytorch-training-loop"

# 文件 → checkpoint 主题映射（按文件名/内容归属）
FILE_CP_MAP = {
    "讲义.md": [  # 讲义按章节分属不同关卡：全部关联到所有关卡（内容覆盖全书）
        "Tensor 与 autograd", "nn.Module 与损失/优化器", "训练循环五步法",
        "完整走读：最小训练循环", "实验与验收",
    ],
    "练习说明.md": ["训练循环五步法", "实验与验收"],
    "data.py": ["训练循环五步法", "实验与验收"],
    "model.py": ["nn.Module 与损失/优化器", "训练循环五步法"],
    "train.py": ["训练循环五步法", "实验与验收"],
}


async def main():
    await init_db()
    async with async_session() as db:
        proj = (await db.execute(
            select(Project).where(Project.name == "PyTorch 训练循环入门")
        )).scalar_one_or_none()
        if not proj:
            print("❌ 项目不存在，先跑 seed_training_loop.py")
            return

        # 1. 找或建 source
        src = (await db.execute(
            select(Source).where(
                Source.project_id == proj.id,
                Source.type == "file",
                Source.url == MATERIALS_DIR,
            )
        )).scalar_one_or_none()
        if not src:
            src = Source(project_id=proj.id, type="file", url=MATERIALS_DIR,
                         status="pending", role="main")
            db.add(src)
            await db.commit()
            await db.refresh(src)
            print(f"[source] created #{src.id}: {MATERIALS_DIR}")
        else:
            print(f"[source] exists #{src.id}")

        # 2. 处理：生成 chunks（先清掉旧的）
        old_chunks = (await db.execute(
            select(Chunk).where(Chunk.source_id == src.id)
        )).scalars().all()
        for c in old_chunks:
            # 解除关联
            links = (await db.execute(
                select(CheckpointChunk).where(CheckpointChunk.chunk_id == c.id)
            )).scalars().all()
            for lk in links:
                await db.delete(lk)
            await db.delete(c)
        await db.commit()

        processor = SourceProcessor()
        src.status = "processing"
        await db.commit()
        try:
            persist_dir = os.path.join(settings.source_cache_dir, str(src.id))
            result = await processor.process_source("file", MATERIALS_DIR, persist_dir=persist_dir)
            chunks_data = result["chunks"]
            print(f"[process] {len(chunks_data)} chunks generated")
        except Exception as e:
            src.status = "failed"
            src.error = str(e)
            await db.commit()
            print(f"❌ 处理失败: {e}")
            return

        # 3. 存 chunks + 关联 checkpoint
        # 先拿到 roadmap 的所有 checkpoint（按标题）
        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.project_id == proj.id)
        )).scalar_one_or_none()
        cps = (await db.execute(
            select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
        )).scalars().all()
        cp_by_title = {c.title: c for c in cps}

        # chunk 的 meta 里有 file 路径（=== 标记切出来的 current_file）
        for i, cd in enumerate(chunks_data):
            chunk = Chunk(
                source_id=src.id,
                index=cd["index"],
                content=cd["content"],
                tokens=cd["tokens"],
                meta_data=cd.get("meta", {}),
            )
            db.add(chunk)
            await db.flush()

            # 根据文件归属关联 checkpoint
            meta = cd.get("meta", {})
            file_name = meta.get("file", "") or meta.get("path", "")
            base_name = os.path.basename(file_name)
            targets = FILE_CP_MAP.get(base_name, [])
            if not targets and "讲义" in file_name:
                targets = [c.title for c in cps]
            for t in targets:
                cp = cp_by_title.get(t)
                if cp:
                    exists = (await db.execute(
                        select(CheckpointChunk).where(
                            CheckpointChunk.checkpoint_id == cp.id,
                            CheckpointChunk.chunk_id == chunk.id,
                        )
                    )).scalar_one_or_none()
                    if not exists:
                        db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=chunk.id))

        src.status = "processed"
        src.meta_data = {"local_path": MATERIALS_DIR, "chunk_count": len(chunks_data)}
        await db.commit()

        # 4. 统计
        total_links = (await db.execute(
            select(CheckpointChunk).join(Chunk).where(Chunk.source_id == src.id)
        )).scalars().all()
        print(f"\n✅ 完成！source #{src.id} 已处理")
        print(f"   chunks: {len(chunks_data)}")
        print(f"   关联: {len(total_links)} 个 checkpoint-chunk 链接")
        for cp in cps:
            n = sum(1 for lk in total_links if lk.checkpoint_id == cp.id)
            print(f"   - {cp.title}: {n} chunks")


if __name__ == "__main__":
    asyncio.run(main())
