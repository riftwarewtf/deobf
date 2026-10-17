-- Deobfuscated by deobf (dynamic trace)
-- source: v15_1_metatable-obfuscated.lua
-- Detected obfuscation: Luraph v15.1
-- NOTE: reconstructed from observed behaviour; branches that were not taken
--       during the trace are missing and conditions are only noted in comments.
-- anti-tamper trap functions disabled: #7
-- run status: finished
-- 65 statements recorded in 0.66s
-- non-standard globals touched: scratch

-- [deobf] folded 6 repeated calls into 1 helper functions and 0 unrolled runs into loops
-- loadstring() of 97174 bytes: "return setmetatable({p=function(r,i,g,T,u,z,X,P)if u<=66 then if u<=65 then local S=r[72](P,2+z);return not(128>S)and 115 or 36,X,g,z,T,S;else return 142,X,g,1+z,T,i;end;elseif u<=67 then return 153,X"
Instance.new("Folder")
local ScreenGui = Instance.new("ScreenGui")
local Frame = Instance.new("Frame")
local Path2D = Instance.new("Path2D")
Frame.Parent = ScreenGui
Path2D.Parent = Frame
ScreenGui:Destroy()
task.wait(0)

task.spawn(function()
	task.wait(0)
end)

task.spawn(function()
end)

task.defer(function()
	-- [envlog] cancelled before it ran
end)

task.delay(786, function()
	-- [envlog] cancelled before it ran
end)

local ScreenGui2 = Instance.new("ScreenGui")
local Frame2 = Instance.new("Frame")
Frame2.Position = UDim2.new(0, 0, 0, 0)
Frame2.Size = UDim2.new(0, 280, 0, 144)
Frame2.Parent = ScreenGui2
local Path2D2 = Instance.new("Path2D")
Path2D2.Parent = Frame2
Path2D2:SetControlPoints({ Path2DControlPoint.new(UDim2.new(0.0625, -10, 0.0625, 4), UDim2.new(0, 5, 0, -2), UDim2.new(0, -8, 0, -5)), Path2DControlPoint.new(UDim2.new(0.3125, -2, 0.125, 5), UDim2.new(-0.125, -2, 0, 6), UDim2.new(0, 0, 0, 0)), Path2DControlPoint.new(UDim2.new(0, 0, 0.125, 2), UDim2.new(0, -2, -0.0625, -2), UDim2.new(0, -6, -0.125, 5)), Path2DControlPoint.new(UDim2.new(0, 0, 0, -4), UDim2.new(0, 3, 0, -7), UDim2.new(0, 0, 0, 0)), Path2DControlPoint.new(UDim2.new(0, -9, 0.25, 7), UDim2.new(-0.125, 2, 0, 7), UDim2.new(0, 1, -0.125, -4)) })
Path2D2:GetLength()
Path2D2:GetPositionOnCurve(0.93333333730697632)
Path2D2:GetPositionOnCurve(0.23076923191547394)
Path2D2:GetPositionOnCurve(0.8571428656578064)
Path2D2:GetPositionOnCurve(0.375)
Path2D2:GetTangentOnCurve(0.75)
Path2D2:GetTangentOnCurve(0.3125)
Path2D2:GetTangentOnCurve(0.3333333432674408)
Path2D2:GetTangentOnCurve(0.45454546809196472)
Path2D2:GetPositionOnCurveArcLength(0.1666666716337204)
Path2D2:GetPositionOnCurveArcLength(0.46666666865348816)
Path2D2:GetPositionOnCurveArcLength(0.18181818723678589)
Path2D2:GetTangentOnCurveArcLength(0.375)
Path2D2:GetTangentOnCurveArcLength(0.66666668653488159)
ScreenGui2:Destroy()

local function onAttributeChanged(value)
	local connection = value.AttributeChanged:Connect(function(attribute)
	end)

	connection:Disconnect()
end

onAttributeChanged(game)
game.ChildAdded:Wait()
onAttributeChanged(workspace)
workspace.ChildAdded:Wait()
local Folder = Instance.new("Folder")
onAttributeChanged(Folder)
Folder.ChildAdded:Wait()
Folder:GetChildren()
Folder:Destroy()
local Folder2 = Instance.new("Folder", Folder)
onAttributeChanged(Folder2)
Folder2.ChildAdded:Wait()
Folder2.Name = "2100133505"
Folder:WaitForChild("2100133505")
Folder:Destroy()
Folder2:Destroy()
local HttpService = game:GetService("HttpService")
onAttributeChanged(HttpService)
HttpService.ChildAdded:Wait()
local RunService = game:GetService("RunService")
onAttributeChanged(RunService)
RunService.ChildAdded:Wait()
