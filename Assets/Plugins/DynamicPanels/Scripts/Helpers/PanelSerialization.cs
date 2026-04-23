using System;
using System.Collections.Generic;
using UnityEngine;

namespace DynamicPanels
{
    public static class PanelSerialization
    {
        #region Helper Classes
        [Serializable]
        private class SerializedCanvas
        {
            public bool active;
            public bool useFreeSpace;

            public SerializedPanelGroup rootPanelGroup;
            public SerializedPanelGroup unanchoredPanelGroup;
        }

        [Serializable]
        private abstract class ISerializedElement
        {
            public Vector2 size;
        }

        [Serializable]
        private class SerializedPanelGroup : ISerializedElement
        {
            public bool horizontal;
            [SerializeReference]
            public ISerializedElement[] children;
        }

        [Serializable]
        private class SerializedDummyPanel : ISerializedElement
        {
        }

        [Serializable]
        private class SerializedPanel : ISerializedElement
        {
            public int activeTab;
            public SerializedPanelTab[] tabs;
            public Vector2 floatingSize;
        }

        [Serializable]
        private class SerializedUnanchoredPanel : SerializedPanel
        {
            public bool active;
            public Vector2 position;
        }

        [Serializable]
        private class SerializedPanelTab
        {
            public string id;
            //public Vector2 minSize;
            //public string label;
        }

        private struct GroupElementSizeHolder
        {
            public IPanelGroupElement element;
            public Vector2 size;

            public GroupElementSizeHolder(IPanelGroupElement element, Vector2 size)
            {
                this.element = element;
                this.size = size;
            }
        }
        #endregion

		private static readonly List<SerializedPanelTab> tabsTemp = new List<SerializedPanelTab>( 4 );
		private static readonly List<GroupElementSizeHolder> sizesHolder = new List<GroupElementSizeHolder>( 4 );

        public static void SerializeCanvas(DynamicPanelsCanvas canvas)
        {
            string json = SerializeCanvasToJson(canvas);
            if (string.IsNullOrEmpty(json))
                return;

            PlayerPrefs.SetString(canvas.ID, json);
            PlayerPrefs.Save();
        }

        public static void DeserializeCanvas(DynamicPanelsCanvas canvas)
        {
            if (PlayerPrefs.HasKey(canvas.ID))
                DeserializeCanvasFromJson(canvas, PlayerPrefs.GetString(canvas.ID, string.Empty));
        }

        public static string SerializeCanvasToJson(DynamicPanelsCanvas canvas, bool prettyPrint = false)
        {
            if (!Application.isPlaying)
            {
                Debug.LogError($"{nameof(PanelSerialization)} works in Play mode only.");
                return null;
            }

            canvas.ForceRebuildLayoutImmediate();

            return JsonUtility.ToJson(new SerializedCanvas
            {
                active = canvas.gameObject.activeSelf,
                useFreeSpace = canvas.LeaveFreeSpace,
                rootPanelGroup = Serialize(canvas.RootPanelGroup) as SerializedPanelGroup,
                unanchoredPanelGroup = Serialize(canvas.UnanchoredPanelGroup) as SerializedPanelGroup,
            }, prettyPrint);
        }

        public static void DeserializeCanvasFromJson(DynamicPanelsCanvas canvas, string json)
        {
            if (!Application.isPlaying)
            {
                Debug.LogError($"{nameof(PanelSerialization)} works in Play mode only.");
                return;
            }

            if (string.IsNullOrEmpty(json))
            {
                Debug.LogError($"{nameof(PanelSerialization)} encountered empty json during deserialization.");
                return;
            }

            if (!json.StartsWith('{'))
            {
                Debug.LogError($"{nameof(PanelSerialization)} encountered invalid json during deserialization.");
                return;
            }

            SerializedCanvas serializedCanvas = JsonUtility.FromJson<SerializedCanvas>(json);
            if (serializedCanvas == null)
            {
                Debug.LogError($"{nameof(PanelSerialization)} couldn't deserialize json.");
                return;
            }

			sizesHolder.Clear();
			canvas.LeaveFreeSpace = serializedCanvas.useFreeSpace;

			if( serializedCanvas.rootPanelGroup != null )
			{
				PanelGroup rootPanelGroup = canvas.RootPanelGroup;
				ISerializedElement[] children = serializedCanvas.rootPanelGroup.children;
				for( int i = children.Length - 1; i >= 0; i-- )
				{
					IPanelGroupElement element = Deserialize( canvas, children[i] );
					if( element != null )
					{
						if( rootPanelGroup.Count == 0 )
							rootPanelGroup.AddElement( element );
						else
							rootPanelGroup.AddElementBefore( rootPanelGroup[0], element );

						sizesHolder.Insert( 0, new GroupElementSizeHolder( element, children[i].size ) );
					}
				}
			}

			if( sizesHolder.Count > 0 )
			{
				canvas.ForceRebuildLayoutImmediate();

				for( int i = 0; i < sizesHolder.Count; i++ )
					sizesHolder[i].element.ResizeTo( sizesHolder[i].size, Direction.Right, Direction.Top );
			}

			if( serializedCanvas.unanchoredPanelGroup != null )
			{
				ISerializedElement[] children = serializedCanvas.unanchoredPanelGroup.children;
				for( int i = 0; i < children.Length; i++ )
				{
					SerializedUnanchoredPanel unanchoredPanel = children[i] as SerializedUnanchoredPanel;
					if( unanchoredPanel != null )
					{
						Panel panel = Deserialize( canvas, unanchoredPanel ) as Panel;
						if( panel != null )
						{
							panel.Detach();
							canvas.UnanchoredPanelGroup.RestrictPanelToBounds( panel );
						}
					}
				}
			}

			for( int i = 0; i < canvas.UnanchoredPanelGroup.Count; i++ )
			{
				Panel panel = canvas.UnanchoredPanelGroup[i] as Panel;
				if( panel != null )
					panel.RectTransform.SetAsLastSibling();
			}

			canvas.gameObject.SetActive( serializedCanvas.active );
		}

		private static ISerializedElement Serialize( IPanelGroupElement element )
		{
			if( element == null )
				return null;

			if( element is Panel )
			{
				Panel panel = (Panel) element;
				if( panel.Internal.IsDummy )
					return new SerializedDummyPanel() { size = panel.Size };

				tabsTemp.Clear();
				for( int i = 0; i < panel.NumberOfTabs; i++ )
				{
					PanelTab tab = panel[i];
					tabsTemp.Add( new SerializedPanelTab()
					{
						id = tab.ID,
						//minSize = tab.MinSize,
						//label = tab.Label
					} );
				}

				if( tabsTemp.Count == 0 )
					return null;

				if( panel.IsDocked )
				{
					return new SerializedPanel()
					{
						activeTab = panel.ActiveTab,
						tabs = tabsTemp.ToArray(),
						size = panel.Size,
						floatingSize = panel.FloatingSize
					};
				}
				else
				{
					return new SerializedUnanchoredPanel()
					{
						active = panel.gameObject.activeSelf,
						activeTab = panel.ActiveTab,
						tabs = tabsTemp.ToArray(),
						position = panel.Position,
						size = panel.Size,
						floatingSize = panel.Size
					};
				}
			}

			PanelGroup panelGroup = (PanelGroup) element;

			ISerializedElement[] children = new ISerializedElement[panelGroup.Count];
			for( int i = 0; i < panelGroup.Count; i++ )
				children[i] = Serialize( panelGroup[i] );

			return new SerializedPanelGroup()
			{
				horizontal = panelGroup.IsInSameDirection( Direction.Right ),
				children = children,
				size = panelGroup.Size
			};
		}

		private static IPanelGroupElement Deserialize( DynamicPanelsCanvas canvas, ISerializedElement element )
		{
			if( element == null )
				return null;

			if( element is SerializedDummyPanel )
				return canvas.Internal.DummyPanel;

			if( element is SerializedPanel )
			{
				SerializedPanel serializedPanel = (SerializedPanel) element;
				Panel panel = null;

				SerializedPanelTab[] tabs = serializedPanel.tabs;
				for( int i = 0; i < tabs.Length; i++ )
				{
					PanelTab tab;
					if( !PanelNotificationCenter.TryGetTab( tabs[i].id, out tab ) )
						continue;

					if( panel == null )
					{
						panel = tab.Detach();
						canvas.UnanchoredPanelGroup.AddElement( panel );
					}
					else
						panel.AddTab( tab );

					//if( tab != null )
					//{
					//	tab.MinSize = tabs[i].minSize;
					//	tab.Label = tabs[i].label;
					//}
				}

				if( panel != null )
				{
					if( serializedPanel.activeTab < tabs.Length )
					{
						int activeTabIndex = panel.GetTabIndex( tabs[serializedPanel.activeTab].id );
						if( activeTabIndex >= 0 )
							panel.ActiveTab = activeTabIndex;
					}

					if( serializedPanel is SerializedUnanchoredPanel )
					{
						SerializedUnanchoredPanel unanchoredPanel = (SerializedUnanchoredPanel) serializedPanel;
						panel.RectTransform.anchoredPosition = unanchoredPanel.position;
						panel.gameObject.SetActive( unanchoredPanel.active );
					}

					panel.FloatingSize = serializedPanel.floatingSize;
				}

				return panel;
			}

			if( element is SerializedPanelGroup )
			{
				SerializedPanelGroup serializedPanelGroup = (SerializedPanelGroup) element;
				ISerializedElement[] children = serializedPanelGroup.children;
				if( children == null || children.Length == 0 )
					return null;

				PanelGroup panelGroup = new PanelGroup( canvas, serializedPanelGroup.horizontal ? Direction.Right : Direction.Top );
				for( int i = 0; i < children.Length; i++ )
				{
					if( children[i] == null )
						continue;

					IPanelGroupElement childElement = Deserialize( canvas, children[i] );
					if( childElement != null )
					{
						panelGroup.AddElement( childElement );
						sizesHolder.Add( new GroupElementSizeHolder( childElement, children[i].size ) );
					}
				}

				if( panelGroup.Count > 0 )
					return panelGroup;
			}

			return null;
		}
	}
}