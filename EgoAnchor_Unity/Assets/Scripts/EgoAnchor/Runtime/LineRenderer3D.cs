/*
 * LineRenderer3D core adapted from:
 * https://github.com/survivorr9049/LineRenderer3D
 * Copyright (c) 2024 survivorr
 *
 * MIT License
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 * FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
 */
using System.Collections.Generic;
using System.Linq;
using Unity.Burst;
using Unity.Collections;
using Unity.Jobs;
using UnityEngine;
using UnityEngine.Rendering;

namespace EgoAnchor.Runtime
{
    /// <summary>
    /// 基于 survivorr9049/LineRenderer3D 的圆管网格生成器。
    /// 原仓库通过环形截面、Job 和 Burst 将一组点转换为真正的三维管体。
    /// </summary>
    /// <remarks>
    /// 来源：https://github.com/survivorr9049/LineRenderer3D/blob/main/Runtime/LineRenderer3D.cs
    /// 本项目保留 Burst 加速，并补充轨迹运行所需的边界保护。
    /// </remarks>
    [System.Serializable]
    public sealed class LineRenderer3D : MonoBehaviour
    {
        /// <summary>是否每帧自动重建；轨迹运行时由外部按采样触发，因此默认关闭。</summary>
        public bool autoUpdate;

        /// <summary>圆环分辨率。</summary>
        public int resolution = 8;

        /// <summary>生成网格使用的材质。</summary>
        public Material material;

        /// <summary>当前采样点列表。</summary>
        [SerializeField] private List<Point> points = new List<Point>();

        /// <summary>MeshFilter 组件。</summary>
        private MeshFilter meshFilter;

        /// <summary>当前输出网格。</summary>
        private Mesh mesh;

        /// <summary>MeshRenderer 组件。</summary>
        private MeshRenderer meshRenderer;

        /// <summary>BeginGenerationAutoComplete 使用的完成标记。</summary>
        private bool autoComplete;

        /// <summary>网格顶点缓存。</summary>
        private NativeArray<Vector3> vertices;

        /// <summary>网格法线缓存。</summary>
        private NativeArray<Vector3> normals;

        /// <summary>网格 UV 缓存。</summary>
        private NativeArray<Vector2> uvs;

        /// <summary>轨迹节点缓存。</summary>
        private NativeArray<Point> nodes;

        /// <summary>网格索引缓存。</summary>
        private NativeArray<int> indices;

        /// <summary>圆环正弦缓存。</summary>
        private NativeArray<float> sines;

        /// <summary>圆环余弦缓存。</summary>
        private NativeArray<float> cosines;

        /// <summary>网格生成 Job。</summary>
        private JobHandle jobHandle;

        /// <summary>点数据 Job。</summary>
        private JobHandle pointsJobHandle;

        /// <summary>截面旋转 Job。</summary>
        private JobHandle rotationJobHandle;

        /// <summary>组件唤醒时复用已有 Mesh 组件或创建一次。</summary>
        private void Awake()
        {
            meshRenderer = GetComponent<MeshRenderer>();
            if (meshRenderer == null)
            {
                meshRenderer = gameObject.AddComponent<MeshRenderer>();
            }
            meshRenderer.shadowCastingMode = ShadowCastingMode.Off;
            meshRenderer.receiveShadows = false;
            meshRenderer.allowOcclusionWhenDynamic = false;
            meshRenderer.sortingOrder = 32767;

            meshFilter = GetComponent<MeshFilter>();
            if (meshFilter == null)
            {
                meshFilter = gameObject.AddComponent<MeshFilter>();
            }

            mesh = meshFilter.sharedMesh;
            if (mesh == null)
            {
                mesh = new Mesh { name = $"{name} Mesh" };
                mesh.MarkDynamic();
                mesh.indexFormat = IndexFormat.UInt32;
                meshFilter.sharedMesh = mesh;
            }
        }

        /// <summary>组件启动时绑定材质。</summary>
        private void Start()
        {
            if (mesh == null)
            {
                mesh = meshFilter.sharedMesh;
            }

            if (material != null)
            {
                meshRenderer.sharedMaterial = material;
            }
        }

        /// <summary>自动更新入口，轨迹组件默认关闭此模式。</summary>
        private void Update()
        {
            if (autoUpdate && Count() >= 2)
            {
                BeginGeneration();
            }
        }

        /// <summary>完成异步网格生成。</summary>
        private void LateUpdate()
        {
            if (autoUpdate)
            {
                CompleteGeneration();
                return;
            }

            if (autoComplete)
            {
                CompleteGeneration();
                autoComplete = false;
            }
        }

        /// <summary>启动一次生成，并在下一次 LateUpdate 提交网格。</summary>
        public void BeginGenerationAutoComplete()
        {
            if (Count() >= 2)
            {
                BeginGeneration();
                autoComplete = true;
            }
        }

        /// <summary>启动圆管网格生成 Job。</summary>

        public void BeginGeneration()
        {
            if (Count() < 2)
            {
                return;
            }

            // 仓库实现会为每轮生成重新分配 TempJob 缓冲；重入前必须先提交并释放上一轮。
            if (!jobHandle.Equals(default(JobHandle)) || HasNativeBuffers())
            {
                CompleteGeneration();
            }

            int sides = Mathf.Clamp(resolution, 6, 24);
            int pointCount = points.Count;
            vertices = new NativeArray<Vector3>(pointCount * sides, Allocator.TempJob);
            normals = new NativeArray<Vector3>(pointCount * sides, Allocator.TempJob);
            uvs = new NativeArray<Vector2>(pointCount * sides, Allocator.TempJob);
            indices = new NativeArray<int>((pointCount - 1) * sides * 6, Allocator.TempJob);
            nodes = new NativeArray<Point>(pointCount, Allocator.TempJob);
            sines = new NativeArray<float>(sides, Allocator.TempJob);
            cosines = new NativeArray<float>(sides, Allocator.TempJob);

            for (int i = 0; i < pointCount; i++)
            {
                nodes[i] = points[i];
            }

            var pointsJob = new CalculatePointData
            {
                nodes = nodes
            };
            pointsJobHandle = pointsJob.Schedule(pointCount - 1, 32);
            pointsJobHandle.Complete();
            CalculateEdgePoints();

            for (int i = 0; i < sides; i++)
            {
                sines[i] = Mathf.Sin(i * Mathf.PI * 2f / sides);
                cosines[i] = Mathf.Cos(i * Mathf.PI * 2f / sides);
            }

            var rotationJob = new FixPointsRotation
            {
                nodes = nodes
            };
            rotationJobHandle = rotationJob.Schedule();
            rotationJobHandle.Complete();

            var meshJob = new Line3D
            {
                resolution = sides,
                indices = indices,
                vertices = vertices,
                sines = sines,
                nodes = nodes,
                cosines = cosines,
                normals = normals,
                uvs = uvs,
                iterations = pointCount
            };
            jobHandle = meshJob.Schedule(pointCount, 16);
            JobHandle.ScheduleBatchedJobs();
        }

        /// <summary>等待生成 Job 并提交网格，随后释放临时缓存。</summary>

        public void CompleteGeneration()
        {
            if (!jobHandle.Equals(default(JobHandle)))
            {
                jobHandle.Complete();

                if (mesh != null)
                {
                    mesh.Clear();
                    mesh.SetVertices(vertices);
                    mesh.SetIndices(indices, MeshTopology.Triangles, 0);
                    mesh.SetNormals(normals);
                    mesh.SetUVs(0, uvs);
                    mesh.RecalculateBounds();
                }
            }

            DisposeNativeBuffers();
            autoComplete = false;
        }

        /// <summary>释放本次生成的 NativeArray。</summary>
        private void DisposeNativeBuffers()
        {
            if (vertices.IsCreated) vertices.Dispose();
            if (indices.IsCreated) indices.Dispose();
            if (sines.IsCreated) sines.Dispose();
            if (cosines.IsCreated) cosines.Dispose();
            if (nodes.IsCreated) nodes.Dispose();
            if (normals.IsCreated) normals.Dispose();
            if (uvs.IsCreated) uvs.Dispose();
            jobHandle = default;
        }

        /// <summary>修正两端圆环的稳定参考方向。</summary>
        private void CalculateEdgePoints()
        {
            nodes[0] = BuildEdgePoint(nodes[0], nodes[1].position - nodes[0].position);
            int last = nodes.Length - 1;
            nodes[last] = BuildEdgePoint(nodes[last], nodes[last].position - nodes[last - 1].position);
        }

        /// <summary>根据边界切线构建带回退轴的圆环节点。</summary>
        private static Point BuildEdgePoint(Point point, Vector3 direction)
        {
            direction = direction.sqrMagnitude > 0.0000001f
                ? direction.normalized
                : Vector3.forward;
            Vector3 reference = Mathf.Abs(Vector3.Dot(direction, Vector3.up)) > 0.95f
                ? Vector3.right
                : Vector3.up;
            Vector3 right = Vector3.Cross(direction, reference).normalized;
            Vector3 up = Vector3.Cross(direction, right).normalized;
            return new Point(point.position, direction, Vector3.zero, up, right, point.thickness);
        }

        /// <summary>初始化指定数量的空轨迹点。</summary>
        public void SetPositions(int positionCount)
        {
            points.Clear();
            Point point = new Point(Vector3.zero, 0f);
            for (int i = 0; i < positionCount; i++)
            {
                points.Add(point);
            }
        }

        /// <summary>移除指定索引的轨迹点。</summary>
        public void RemovePoint(int index)
        {
            points.RemoveAt(index);
        }

        /// <summary>追加一个带半径的轨迹点。</summary>
        public void AddPoint(Vector3 position, float thickness)
        {
            points.Add(new Point(position, thickness));
        }

        /// <summary>修改指定索引的轨迹点。</summary>
        public void SetPoint(int index, Vector3 position, float thickness)
        {
            points[index] = new Point(position, thickness);
        }

        /// <summary>设置统一半径的一组点。</summary>
        public void SetPoints(Vector3[] positions, float thickness)
        {
            points = positions.Select(position => new Point(position, thickness)).ToList();
        }

        /// <summary>设置每个点半径不同的一组点。</summary>
        public void SetPoints(Vector3[] positions, float[] thicknesses)
        {
            points = positions.Zip(thicknesses, (position, thickness) => new Point(position, thickness)).ToList();
        }

        /// <summary>获取当前点数量。</summary>
        public int Count()
        {
            return points.Count;
        }

        /// <summary>获取指定轨迹点。</summary>
        public Point GetPoint(int index)
        {
            return points[index];
        }

        /// <summary>轨迹点及其截面方向数据。</summary>
        [System.Serializable]
        public struct Point
        {
            /// <summary>点位置。</summary>
            public Vector3 position;

            /// <summary>点的切线方向。</summary>
            [HideInInspector] public Vector3 direction;

            /// <summary>点的弯曲法向。</summary>
            [HideInInspector] public Vector3 normal;

            /// <summary>点的环面上方向。</summary>
            [HideInInspector] public Vector3 up;

            /// <summary>点的环面右方向。</summary>
            [HideInInspector] public Vector3 right;

            /// <summary>点的圆管半径。</summary>
            public float thickness;

            /// <summary>完整构造轨迹点。</summary>
            public Point(Vector3 position, Vector3 direction, Vector3 normal, Vector3 up, Vector3 right, float thickness)
            {
                this.position = position;
                this.direction = direction;
                this.normal = normal;
                this.thickness = thickness;
                this.up = up;
                this.right = right;
            }

            /// <summary>用位置和半径构造轨迹点。</summary>
            public Point(Vector3 position, float thickness)
            {
                this.position = position;
                this.direction = Vector3.zero;
                this.normal = Vector3.zero;
                this.thickness = thickness;
                this.up = Vector3.zero;
                this.right = Vector3.zero;
            }
        }

        /// <summary>为每个轨迹点生成圆环顶点和侧面索引。</summary>

        [BurstCompile]
        public struct Line3D : IJobParallelFor
        {
            /// <summary>截面分段数。</summary>
            public int resolution;

            /// <summary>轨迹点数量。</summary>
            public int iterations;

            /// <summary>轨迹节点。</summary>
            [ReadOnly] public NativeArray<Point> nodes;

            /// <summary>预计算正弦。</summary>
            [ReadOnly] public NativeArray<float> sines;

            /// <summary>预计算余弦。</summary>
            [ReadOnly] public NativeArray<float> cosines;

            /// <summary>输出顶点。</summary>
            [NativeDisableParallelForRestriction] public NativeArray<Vector3> vertices;

            /// <summary>输出索引。</summary>
            [NativeDisableParallelForRestriction] public NativeArray<int> indices;

            /// <summary>输出法线。</summary>
            [NativeDisableParallelForRestriction] public NativeArray<Vector3> normals;

            /// <summary>输出 UV。</summary>
            [NativeDisableParallelForRestriction] public NativeArray<Vector2> uvs;

                        /// <summary>生成一个轨迹点对应的圆环。</summary>
            public void Execute(int i)
            {
                Vector3 right = nodes[i].right.normalized * nodes[i].thickness;
                Vector3 up = nodes[i].up.normalized * nodes[i].thickness;
                for (int j = 0; j < resolution; j++)
                {
                    int vertexIndex = i * resolution + j;
                    Vector3 vertexOffset = cosines[j] * right + sines[j] * up;

                    // 沿仓库实现的转折法向修正截面，使急转弯处的相邻圆环保持连续。
                    Vector3 bendNormal = nodes[i].normal.sqrMagnitude > 0.0000001f
                        ? nodes[i].normal.normalized
                        : Vector3.zero;
                    if (bendNormal.sqrMagnitude > 0.0000001f)
                    {
                        float correction = Mathf.Clamp(1f / nodes[i].normal.magnitude, 0f, 2f) - 1f;
                        vertexOffset += bendNormal * Vector3.Dot(bendNormal, vertexOffset) * correction;
                    }

                    vertices[vertexIndex] = nodes[i].position + vertexOffset;
                    normals[vertexIndex] = vertexOffset.sqrMagnitude > 0.0000001f
                        ? vertexOffset.normalized
                        : Vector3.up;
                    uvs[vertexIndex] = new Vector2(i, (float)j / (resolution - 1));

                    if (i == iterations - 1)
                    {
                        continue;
                    }

                    int offset = i * resolution * 6 + j * 6;
                    int nextSide = (j + 1) % resolution;
                    indices[offset] = j + i * resolution;
                    indices[offset + 1] = nextSide + i * resolution;
                    indices[offset + 2] = j + resolution + i * resolution;
                    indices[offset + 3] = nextSide + i * resolution;
                    indices[offset + 4] = nextSide + resolution + i * resolution;
                    indices[offset + 5] = j + resolution + i * resolution;
                }
            }
        }

        /// <summary>根据相邻点计算内部节点的切线和圆环方向。</summary>

        [BurstCompile]
        public struct CalculatePointData : IJobParallelFor
        {
            /// <summary>轨迹节点缓存。</summary>
            [NativeDisableParallelForRestriction] public NativeArray<Point> nodes;

            /// <summary>计算内部节点方向。</summary>
            public void Execute(int i)
            {
                if (i == 0 || i >= nodes.Length - 1)
                {
                    return;
                }

                Vector3 previous = (nodes[i].position - nodes[i - 1].position).normalized;
                Vector3 next = (nodes[i + 1].position - nodes[i].position).normalized;
                Vector3 direction = previous + next;
                if (direction.sqrMagnitude < 0.0000001f)
                {
                    direction = next.sqrMagnitude > 0.0000001f ? next : previous;
                }

                direction = direction.sqrMagnitude > 0.0000001f
                    ? direction.normalized
                    : Vector3.forward;
                Vector3 normal = (next - previous).normalized * Mathf.Abs(Vector3.Dot(previous, direction));
                Vector3 reference = Mathf.Abs(Vector3.Dot(direction, Vector3.up)) > 0.95f
                    ? Vector3.right
                    : Vector3.up;
                Vector3 right = Vector3.Cross(direction, reference).normalized;
                Vector3 up = Vector3.Cross(direction, right).normalized;
                nodes[i] = new Point(nodes[i].position, direction, normal, up, right, nodes[i].thickness);
            }
        }

        /// <summary>沿转折方向修正相邻圆环的滚转，减少轨迹接缝扭转。</summary>

        [BurstCompile]
        public struct FixPointsRotation : IJob
        {
            /// <summary>轨迹节点缓存。</summary>
            public NativeArray<Point> nodes;

            /// <summary>执行圆环方向的连续化。</summary>
            public void Execute()
            {
                for (int i = 0; i < nodes.Length - 1; i++)
                {
                    Vector3 fromTo = (nodes[i + 1].position - nodes[i].position).normalized;
                    if (fromTo.sqrMagnitude < 0.0000001f)
                    {
                        continue;
                    }

                    Vector3 firstRight = nodes[i].right - Vector3.Dot(nodes[i].right, fromTo) * fromTo;
                    Vector3 secondRight = nodes[i + 1].right - Vector3.Dot(nodes[i + 1].right, fromTo) * fromTo;
                    if (firstRight.sqrMagnitude < 0.0000001f || secondRight.sqrMagnitude < 0.0000001f)
                    {
                        continue;
                    }

                    float angle = -Vector3.SignedAngle(firstRight, secondRight, fromTo);
                    Quaternion rotation = Quaternion.AngleAxis(angle, nodes[i + 1].direction);
                    nodes[i + 1] = new Point(
                        nodes[i + 1].position,
                        nodes[i + 1].direction,
                        nodes[i + 1].normal,
                        rotation * nodes[i + 1].up,
                        rotation * nodes[i + 1].right,
                        nodes[i + 1].thickness);
                }
            }
        }

        /// <summary>组件停用前完成任务并释放 TempJob 缓冲。</summary>
        private void OnDisable()
        {
            CompleteGeneration();
        }

        /// <summary>判断是否仍持有任一轮圆管生成的临时缓冲。</summary>
        private bool HasNativeBuffers()
        {
            return vertices.IsCreated ||
                   normals.IsCreated ||
                   uvs.IsCreated ||
                   nodes.IsCreated ||
                   indices.IsCreated ||
                   sines.IsCreated ||
                   cosines.IsCreated;
        }

        /// <summary>销毁生成 Job 和运行时网格。</summary>
        private void OnDestroy()
        {
            if (!jobHandle.Equals(default(JobHandle)))
            {
                jobHandle.Complete();
            }

            DisposeNativeBuffers();
            if (mesh != null)
            {
                Destroy(mesh);
            }
        }
    }
}

